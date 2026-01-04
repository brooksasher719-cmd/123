import React, { useEffect, useRef } from 'react';
import { marked } from 'marked';
import { Bold, Italic, Heading1, Heading2, Heading3, Undo, Redo, Eraser, AlignRight, AlignLeft, AlignCenter } from 'lucide-react';

interface RichTextEditorProps {
  content: string;
  onContentChange: (newContent: string) => void;
  isReadOnly: boolean;
  placeholder?: string;
}

const RichTextEditor: React.FC<RichTextEditorProps> = ({ 
  content, 
  onContentChange, 
  isReadOnly,
  placeholder 
}) => {
  const editorRef = useRef<HTMLDivElement>(null);
  
  // Helper: Detect if string is HTML or needs Markdown parsing
  const getHtml = (c: string) => {
    if (!c) return '';
    // If it starts with a tag or contains clear HTML tags, assume HTML
    // This prevents re-parsing HTML as Markdown which breaks structure
    const hasTags = /<[a-z][\s\S]*>/i.test(c) || /&[a-z]+;/i.test(c);
    if (hasTags) return c; 
    return marked.parse(c, { breaks: true }) as string;
  };

  // Sync content from parent to editor DOM
  useEffect(() => {
    if (!editorRef.current) return;
    
    const targetHtml = getHtml(content);
    const currentHtml = editorRef.current.innerHTML;

    // CRITICAL: Only update DOM if content is significantly different.
    // This prevents cursor jumping and input interruption when typing.
    if (currentHtml !== targetHtml) {
        // If the lengths differ significantly or content is totally different, update.
        // For exact typing sync, strict equality check is usually enough if the parent 
        // sends back exactly what we sent it.
        editorRef.current.innerHTML = targetHtml;
    }
  }, [content]);

  // Handle user typing
  const handleInput = (e: React.FormEvent<HTMLDivElement>) => {
    if (isReadOnly) return;
    const newHtml = e.currentTarget.innerHTML;
    onContentChange(newHtml);
  };

  // Prevent default behavior for enter if needed, or handle special keys
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (isReadOnly) {
      e.preventDefault();
    }
  };

  // --- Formatting Commands ---
  const execCmd = (command: string, value: string | undefined = undefined) => {
    if (isReadOnly) return;
    
    // Ensure focus is on the editor before executing
    if (editorRef.current) {
      editorRef.current.focus();
    }

    document.execCommand(command, false, value);
    
    // Force update state after command
    if (editorRef.current) {
      const newHtml = editorRef.current.innerHTML;
      onContentChange(newHtml);
    }
  };

  const ToolbarButton = ({ icon: Icon, cmd, arg, title }: { icon: any, cmd: string, arg?: string, title: string }) => (
    <button
      onMouseDown={(e) => {
        e.preventDefault(); // Critical: Prevents editor blur
        execCmd(cmd, arg);
      }}
      className={`p-2 rounded-lg transition-all active:scale-95 flex items-center justify-center
        ${isReadOnly 
          ? 'text-slate-300 cursor-not-allowed' 
          : 'text-slate-600 hover:bg-indigo-50 hover:text-indigo-600 hover:shadow-sm'
        }`}
      title={title}
      disabled={isReadOnly}
    >
      <Icon size={18} strokeWidth={2.5} />
    </button>
  );

  return (
    <div className="flex flex-col h-full bg-white relative group">
      {/* Sticky Toolbar */}
      <div className={`
        flex items-center gap-1 p-2 border-b border-slate-100 bg-white/95 backdrop-blur z-10 sticky top-0
        transition-opacity duration-200 flex-wrap
        ${isReadOnly ? 'opacity-60 grayscale pointer-events-none' : 'opacity-100'}
      `}>
        {/* Text Style */}
        <div className="flex items-center gap-0.5 bg-slate-50 p-1 rounded-lg border border-slate-200">
          <ToolbarButton icon={Bold} cmd="bold" title="بولد (Ctrl+B)" />
          <ToolbarButton icon={Italic} cmd="italic" title="ایتالیک (Ctrl+I)" />
        </div>
        
        <div className="w-px h-6 bg-slate-200 mx-1"></div>
        
        {/* Headings */}
        <div className="flex items-center gap-0.5 bg-slate-50 p-1 rounded-lg border border-slate-200">
          <ToolbarButton icon={Heading1} cmd="formatBlock" arg="H1" title="تیتر 1" />
          <ToolbarButton icon={Heading2} cmd="formatBlock" arg="H2" title="تیتر 2" />
          <ToolbarButton icon={Heading3} cmd="formatBlock" arg="H3" title="تیتر 3" />
        </div>

        <div className="w-px h-6 bg-slate-200 mx-1"></div>

        {/* Alignment */}
        <div className="flex items-center gap-0.5 bg-slate-50 p-1 rounded-lg border border-slate-200">
           <ToolbarButton icon={AlignRight} cmd="justifyRight" title="راست‌چین" />
           <ToolbarButton icon={AlignCenter} cmd="justifyCenter" title="وسط‌چین" />
           <ToolbarButton icon={AlignLeft} cmd="justifyLeft" title="چپ‌چین" />
        </div>

        <div className="flex items-center gap-0.5 mr-auto">
             <button
              onMouseDown={(e) => { e.preventDefault(); execCmd('removeFormat'); }}
              className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition"
              title="پاک کردن فرمت"
              disabled={isReadOnly}
            >
              <Eraser size={18} />
            </button>
            <div className="w-px h-4 bg-slate-200 mx-1"></div>
            <ToolbarButton icon={Undo} cmd="undo" title="بازگشت" />
            <ToolbarButton icon={Redo} cmd="redo" title="انجام مجدد" />
        </div>
      </div>

      {/* Editor Area */}
      <div className="relative flex-1 overflow-hidden flex flex-col">
        {!content && (
          <div className="absolute top-8 right-6 text-slate-400 pointer-events-none z-0">
            {placeholder || 'شروع به تایپ کنید...'}
          </div>
        )}
        
        <div
          ref={editorRef}
          className={`
            editor-content w-full flex-1 p-6 outline-none overflow-y-auto 
            text-slate-800 leading-8 text-right font-[Vazirmatn,Tahoma]
            selection:bg-indigo-100 selection:text-indigo-900
            ${isReadOnly ? 'bg-slate-50 cursor-default' : 'bg-white cursor-text'}
          `}
          contentEditable={!isReadOnly}
          onInput={handleInput}
          onKeyDown={handleKeyDown}
          suppressContentEditableWarning={true}
          dir="rtl"
        />
      </div>
    </div>
  );
};

export default RichTextEditor;