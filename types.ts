export enum ProcessingStage {
  RAW = 'RAW', // Initial Transcription
  ARABIC = 'ARABIC', // Arabic highlighting
  TITLES = 'TITLES', // Tree structuring
  FORMAL = 'FORMAL', // Colloquial to Formal
  CUSTOM = 'CUSTOM', // Custom prompt
}

export interface Version {
  id: string;
  stage: ProcessingStage;
  name: string;
  content: string;
  parentId: string | null;
  timestamp: number;
  promptUsed?: string;
}

export interface MediaItem {
  id: string;
  file: File;
  duration: number; // in seconds
  status: 'idle' | 'uploading' | 'processing' | 'paused' | 'completed' | 'error';
  progress: number; // 0-100
  currentVersionId: string | null;
  versions: Version[];
  error?: string;
  // Simulating the "chunks" logic visually and logically
  processedChunks: number; 
  totalChunks: number;
}

export interface PlayerState {
  isPlaying: boolean;
  currentTime: number;
  playbackRate: number;
  volume: number;
}