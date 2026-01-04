import React, { useRef, useEffect, useState } from 'react';
import { Play, Pause, SkipForward, SkipBack, Gauge, Volume2, VolumeX, CloudOff } from 'lucide-react';

interface MediaPlayerProps {
  file: File | null;
  // Support for cloud restored items which might store filename separately
  fileName?: string; 
  onEnded: () => void;
}

const MediaPlayer: React.FC<MediaPlayerProps> = ({ file, fileName, onEnded }) => {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [duration, setDuration] = useState(0);
  const [rate, setRate] = useState(1);
  const [volume, setVolume] = useState(1);
  const [isMuted, setIsMuted] = useState(false);
  const [objectUrl, setObjectUrl] = useState<string | null>(null);

  useEffect(() => {
    if (file) {
      const url = URL.createObjectURL(file);
      setObjectUrl(url);
      return () => {
        URL.revokeObjectURL(url);
        setObjectUrl(null);
      };
    } else {
      setObjectUrl(null);
    }
  }, [file]);

  const togglePlay = () => {
    if (audioRef.current) {
      if (isPlaying) audioRef.current.pause();
      else audioRef.current.play();
      setIsPlaying(!isPlaying);
    }
  };

  const handleTimeUpdate = () => {
    if (audioRef.current) {
      setProgress(audioRef.current.currentTime);
      setDuration(audioRef.current.duration || 0);
    }
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (audioRef.current) {
      const time = Number(e.target.value);
      audioRef.current.currentTime = time;
      setProgress(time);
    }
  };

  const changeRate = () => {
    const rates = [1, 1.25, 1.5, 2, 0.5, 0.75];
    const currentIndex = rates.indexOf(rate);
    const nextRate = rates[(currentIndex + 1) % rates.length];
    setRate(nextRate);
    if (audioRef.current) audioRef.current.playbackRate = nextRate;
  };

  const formatTime = (seconds: number) => {
    if (!seconds) return "00:00";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  // Condition 1: No file selected at all
  if (!file && !fileName) return null;

  // Condition 2: Cloud item (Filename exists but File object is null)
  if (!file && fileName) {
    return (
        <div className="w-full bg-slate-900 text-white p-4 rounded-xl shadow-2xl flex flex-col gap-3 items-center justify-center text-center py-8 border border-slate-700">
           <CloudOff size={32} className="text-slate-500 mb-2" />
           <h3 className="font-medium text-slate-300">{fileName}</h3>
           <p className="text-xs text-slate-500 max-w-md">
             این فایل از فضای ابری بازگردانی شده است. فایل صوتی اصلی در دیتابیس ذخیره نشده است، اما تمام متون و ویرایش‌ها در دسترس هستند.
           </p>
        </div>
    );
  }

  // Condition 3: Normal playback
  if (!objectUrl) return null;

  return (
    <div className="w-full bg-slate-900 text-white p-4 rounded-xl shadow-2xl flex flex-col gap-3">
      {/* Hidden Audio Element */}
      <audio
        ref={audioRef}
        src={objectUrl}
        onTimeUpdate={handleTimeUpdate}
        onEnded={() => { setIsPlaying(false); onEnded(); }}
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
      />

      {/* Title */}
      <div className="flex items-center justify-between text-sm text-slate-300">
        <span className="truncate max-w-[70%] font-medium">{fileName || file?.name}</span>
        <span className="font-mono">{formatTime(progress)} / {formatTime(duration)}</span>
      </div>

      {/* Progress Bar */}
      <div className="relative w-full h-2 group cursor-pointer">
        <div className="absolute top-0 left-0 w-full h-full bg-slate-700 rounded-full overflow-hidden">
          <div 
            className="h-full bg-indigo-500 transition-all duration-100 ease-linear"
            style={{ width: `${(progress / duration) * 100}%` }}
          />
        </div>
        <input 
          type="range" 
          min={0} 
          max={duration || 0} 
          value={progress} 
          onChange={handleSeek}
          className="absolute top-0 left-0 w-full h-full opacity-0 cursor-pointer"
        />
      </div>

      {/* Controls */}
      <div className="flex items-center justify-between mt-1">
        
        {/* Playback Speed */}
        <button 
          onClick={changeRate}
          className="flex items-center gap-1 text-xs font-bold text-slate-400 hover:text-white transition-colors bg-slate-800 px-2 py-1 rounded"
        >
          <Gauge size={14} />
          {rate}x
        </button>

        {/* Main Controls */}
        <div className="flex items-center gap-4">
          <button 
             onClick={() => { if(audioRef.current) audioRef.current.currentTime -= 10; }}
             className="text-slate-400 hover:text-white"
          >
            <SkipBack size={20} />
          </button>
          
          <button 
            onClick={togglePlay}
            className="bg-indigo-600 hover:bg-indigo-500 text-white p-3 rounded-full transition-transform active:scale-95 shadow-lg shadow-indigo-900/50"
          >
            {isPlaying ? <Pause size={24} fill="currentColor" /> : <Play size={24} fill="currentColor" className="ml-1" />}
          </button>

          <button 
             onClick={() => { if(audioRef.current) audioRef.current.currentTime += 10; }}
             className="text-slate-400 hover:text-white"
          >
            <SkipForward size={20} />
          </button>
        </div>

        {/* Volume */}
        <div className="flex items-center gap-2 group relative">
          <button onClick={() => setIsMuted(!isMuted)} className="text-slate-400 hover:text-white">
            {isMuted ? <VolumeX size={18} /> : <Volume2 size={18} />}
          </button>
          <input 
             type="range"
             min="0"
             max="1"
             step="0.01"
             value={isMuted ? 0 : volume}
             onChange={(e) => {
               const val = Number(e.target.value);
               setVolume(val);
               setIsMuted(val === 0);
               if(audioRef.current) audioRef.current.volume = val;
             }}
             className="w-20 accent-indigo-500 h-1 bg-slate-700 rounded-lg cursor-pointer opacity-0 group-hover:opacity-100 transition-opacity absolute bottom-full -right-6 -rotate-90 origin-bottom-left bg-slate-800 p-2 shadow-xl border border-slate-700" 
          />
        </div>
      </div>
    </div>
  );
};

export default MediaPlayer;