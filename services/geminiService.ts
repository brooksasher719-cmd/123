import { GoogleGenAI } from "@google/genai";
import { ProcessingStage } from '../types';

// Declare global variable for lamejs loaded via script tag
declare global {
  interface Window {
    lamejs: any;
  }
}

// --- Audio Processing Utilities ---

// Convert AudioBuffer to MP3 Blob using lamejs
const convertBufferToMp3 = (buffer: AudioBuffer): Blob => {
  const channels = 1; // Mono
  const sampleRate = buffer.sampleRate; // Should be 16000 from resample step
  const kbps = 64; // Bitrate

  if (!window.lamejs) {
    throw new Error("Lamejs library not loaded");
  }

  const mp3encoder = new window.lamejs.Mp3Encoder(channels, sampleRate, kbps);
  const mp3Data = [];

  // Get samples (Float32)
  const samples = buffer.getChannelData(0);
  
  // Convert Float32 to Int16 for lamejs
  const sampleData = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    // Clamp and scale
    const s = Math.max(-1, Math.min(1, samples[i]));
    sampleData[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
  }

  // Encode
  const blockSize = 1152;
  for (let i = 0; i < sampleData.length; i += blockSize) {
    const sampleChunk = sampleData.subarray(i, i + blockSize);
    const mp3buf = mp3encoder.encodeBuffer(sampleChunk);
    if (mp3buf.length > 0) {
      mp3Data.push(mp3buf);
    }
  }

  // Flush
  const mp3buf = mp3encoder.flush();
  if (mp3buf.length > 0) {
    mp3Data.push(mp3buf);
  }

  return new Blob(mp3Data, { type: 'audio/mp3' });
};

// Decode the entire audio file into an AudioBuffer
export const decodeAudioFile = async (file: File): Promise<AudioBuffer> => {
  const arrayBuffer = await file.arrayBuffer();
  // Attempt to use a lower sample rate context
  const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 16000 });
  return await audioContext.decodeAudioData(arrayBuffer);
};

// Slice the AudioBuffer, resample to 16kHz mono, ENCODE TO MP3, and return Blob
export const sliceAudioBuffer = async (
  fullBuffer: AudioBuffer, 
  startTime: number, 
  duration: number
): Promise<Blob> => {
  // Target sample rate for speech recognition
  const TARGET_SAMPLE_RATE = 16000;
  
  const sourceTotalDuration = fullBuffer.duration;
  
  // If start time is beyond duration, return empty
  if (startTime >= sourceTotalDuration) {
    return new Blob([], { type: 'audio/mp3' });
  }

  // Calculate actual duration for this chunk
  const actualDuration = Math.min(duration, sourceTotalDuration - startTime);
  const lengthInSamples = Math.ceil(actualDuration * TARGET_SAMPLE_RATE);

  // Use OfflineAudioContext to resample
  const offlineCtx = new OfflineAudioContext(1, lengthInSamples, TARGET_SAMPLE_RATE);
  
  const source = offlineCtx.createBufferSource();
  source.buffer = fullBuffer;
  source.connect(offlineCtx.destination);
  
  source.start(0, startTime, actualDuration);
  
  const renderedBuffer = await offlineCtx.startRendering();

  // CONVERT TO MP3
  return convertBufferToMp3(renderedBuffer);
};

export const blobToBase64 = async (blob: Blob): Promise<string> => {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onloadend = () => {
            const result = reader.result as string;
            // Handle both data:audio/mp3;base64,..... and just base64
            if (result.includes(',')) {
              resolve(result.split(',')[1]);
            } else {
              resolve(result);
            }
        };
        reader.onerror = reject;
        reader.readAsDataURL(blob);
    });
};

export const createGenAIClient = (apiKey: string) => {
  return new GoogleGenAI({ apiKey });
};

// Helper to clean markdown code blocks often returned by LLMs
const cleanResponse = (text: string) => {
  return text.replace(/^```(markdown|html)?\s*/i, '').replace(/\s*```$/, '').trim();
};

/**
 * Transcribes a pre-sliced audio chunk with Retry and Fallback logic.
 */
export const transcribeSegment = async (
  apiKey: string,
  audioChunkBase64: string,
  mimeType: string,
  selectedModel: string = 'gemini-2.5-pro-preview'
): Promise<string> => {
  const ai = createGenAIClient(apiKey);
  
  const prompt = `
    You are a professional verbatim transcriber. 
    
    STRICT RULES:
    1. Transcribe the audio EXACTLY word-for-word in the original language (Persian/Farsi).
    2. Do NOT summarize, do NOT delete repeated words, do NOT fix grammar.
    3. Do NOT add any introductory text like "Here is the text" or "Transcription:".
    4. Return ONLY the transcript text.
    5. If silence, return empty string.
  `;

  // Fallback chain including 2.5 Pro and Flash
  const MODELS_TO_TRY = [
    selectedModel, 
    'gemini-3-flash-preview',
    'gemini-2.5-pro-preview',
    'gemini-2.5-flash-preview',
    'gemini-2.0-flash-exp',
    'gemini-1.5-flash'
  ];
  
  // Remove duplicates in case selected model is one of the fallbacks
  const uniqueModels = [...new Set(MODELS_TO_TRY)];

  let lastError: any = null;

  for (const model of uniqueModels) {
    // 3 Retries per model
    for (let attempt = 1; attempt <= 3; attempt++) {
      try {
        console.log(`Attempt ${attempt} using model: ${model}`);
        
        const response = await ai.models.generateContent({
          model: model,
          contents: {
            parts: [
              {
                inlineData: {
                  mimeType: 'audio/mp3', // Explicitly MP3
                  data: audioChunkBase64
                }
              },
              { text: prompt }
            ]
          },
          config: {
             // Only use thinking for Pro models/2.0 to avoid errors on simple Flash
             thinkingConfig: (model.includes('pro') || model.includes('2.0') || model.includes('2.5')) ? undefined : undefined 
          }
        });
        
        return cleanResponse(response.text || "");
      } catch (error: any) {
        console.warn(`Error with ${model} (Attempt ${attempt}):`, error);
        lastError = error;
        
        // Wait before retry (Exponential backoff: 1s, 2s, 4s)
        await new Promise(resolve => setTimeout(resolve, 1000 * Math.pow(2, attempt - 1)));
      }
    }
    console.warn(`Model ${model} failed after 3 attempts. Switching to fallback...`);
  }

  console.error("All models failed.", lastError);
  throw lastError || new Error("Transcription failed after multiple attempts.");
};

/**
 * Handles the post-processing stages (Arabic, Titles, Formal, Custom)
 */
export const processTextStage = async (
  apiKey: string,
  text: string,
  stage: ProcessingStage,
  selectedModel: string = 'gemini-2.5-pro-preview',
  customPrompt?: string
): Promise<string> => {
  const ai = createGenAIClient(apiKey);
  
  let systemInstruction = "";
  let userPrompt = "";

  switch (stage) {
    case ProcessingStage.ARABIC:
      systemInstruction = "You are an expert Persian/Arabic linguist and text formatter.";
      userPrompt = `
        JOB:
        1. Identify all Arabic text segments (Quranic verses, Hadiths, Arabic phrases) within the Persian input.
        2. **CRITICAL:** ADD FULL DIACRITICS (Tashkeel/Erab) to these identified Arabic segments. The output MUST have diacritics.
        3. Wrap these Arabic segments with guillemets (« »).
        4. Bold these Arabic segments using HTML <strong> tags (NOT markdown stars).
        
        EXAMPLE:
        Input: قال علی علیه السلام الصبر مفتاح الفرج
        Output: قال علی علیه السلام «<strong>الصَّبْرُ مِفْتَاحُ الْفَرَجِ</strong>»

        STRICT RULES:
        - Use HTML <strong> tags for bolding.
        - Do NOT touch Persian text.
        - Do NOT summarize.
        - Return the FULL text.
        
        Input Text:
        ${text}
      `;
      break;

    case ProcessingStage.TITLES:
      systemInstruction = "You are a content structurer.";
      userPrompt = `
        Task: Add hierarchical headers (H1, H2, H3) to the text based on topic changes.
        
        STRICT RULES:
        1. Use HTML headers (<h1>, <h2>, <h3>). Do NOT use Markdown (#).
        2. CRITICAL: Do NOT change, delete, or summarize the body text. 
        3. Keep the paragraphs word-for-word identical to the input.
        4. Only INSERT headers between paragraphs.
        5. Headers must be in Persian and descriptive.
        6. Output the FULL text with new headers embedded.
        
        Input Text:
        ${text}
      `;
      break;

    case ProcessingStage.FORMAL:
      systemInstruction = "You are a Persian language expert.";
      userPrompt = `
        Task: Convert colloquial Persian words (محاوره‌ای) to Formal Persian words (رسمی).
        
        STRICT RULES:
        1. Process the text word-by-word.
        2. CRITICAL: Do NOT summarize. Do NOT delete sentences. Do NOT rewrite the meaning.
        3. ONLY change the morphology of words (e.g., 'میشه' -> 'می‌شود', 'خونه' -> 'خانه').
        4. If a word is already formal, keep it exactly as is.
        5. The output language MUST be Persian.
        
        Input Text:
        ${text}
      `;
      break;

    case ProcessingStage.CUSTOM:
      systemInstruction = "You are a versatile text editor.";
      userPrompt = `
        ${customPrompt}
        
        STRICT RULES:
        1. Unless explicitly told to summarize, do NOT summarize.
        2. Unless explicitly told to change language, keep output in Persian.
        3. Apply the user's instructions to the text.
        
        Input Text:
        ${text}
      `;
      break;
      
    default:
      throw new Error("Invalid stage");
  }

  // Fallback models for text processing including 2.5 Pro and Flash
  const MODELS = [selectedModel, 'gemini-3-flash-preview', 'gemini-2.5-pro-preview', 'gemini-2.5-flash-preview', 'gemini-2.0-flash-exp', 'gemini-1.5-flash'];
  const uniqueModels = [...new Set(MODELS)];

  for (const model of uniqueModels) {
    try {
        const response = await ai.models.generateContent({
            model: model,
            contents: userPrompt,
            config: {
              systemInstruction: systemInstruction,
              // Thinking helps with complex tasks like Erab
              // Enabled for Pro, 2.5 series, and 3.0 series
              thinkingConfig: (stage === ProcessingStage.ARABIC && (model.includes('pro') || model.includes('thinking') || model.includes('2.5') || model.includes('3.0'))) 
                ? { thinkingBudget: 2048 } 
                : undefined
            }
        });
        return cleanResponse(response.text || "");
    } catch (e) {
        console.warn(`Text processing failed on ${model}, trying next...`);
        if (model === uniqueModels[uniqueModels.length -1]) throw e;
    }
  }
  return "";
};