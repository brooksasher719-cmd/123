import React, { useEffect, useState, useMemo } from 'react';
import { 
  X, 
  Search, 
  Trash2, 
  CloudDownload, 
  Calendar, 
  Clock, 
  FileAudio, 
  Loader2,
  AlertCircle,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  AlertTriangle
} from 'lucide-react';
import { loadProjectsFromSupabase, deleteProjectFromSupabase, SavedProject } from '../services/supabaseClient';
import { MediaItem } from '../types';

interface FileManagerProps {
  isOpen: boolean;
  onClose: () => void;
  onLoadProject: (item: MediaItem) => void;
}

type SortKey = 'fileName' | 'updated_at' | 'status';

const FileManager: React.FC<FileManagerProps> = ({ isOpen, onClose, onLoadProject }) => {
  const [projects, setProjects] = useState<SavedProject[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [sortConfig, setSortConfig] = useState<{ key: SortKey; direction: 'asc' | 'desc' }>({ key: 'updated_at', direction: 'desc' });
  
  // New state for custom confirmation modal
  const [deleteConfirmation, setDeleteConfirmation] = useState<{ isOpen: boolean; id: string | null }>({ isOpen: false, id: null });

  useEffect(() => {
    if (isOpen) {
      fetchProjects();
    }
  }, [isOpen]);

  const fetchProjects = async () => {
    try {
      setLoading(true);
      const data = await loadProjectsFromSupabase();
      setProjects(data);
      setError(null);
    } catch (err: any) {
      setError('خطا در دریافت لیست پروژه‌ها: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const promptDelete = (id: string, e: React.MouseEvent) => {
    e.preventDefault(); 
    e.stopPropagation();
    // Open custom modal instead of window.confirm
    setDeleteConfirmation({ isOpen: true, id });
  };

  const performDelete = async () => {
    const id = deleteConfirmation.id;
    if (!id) return;

    // Close confirmation modal immediately
    setDeleteConfirmation({ isOpen: false, id: null });

    try {
      setDeletingId(id);
      await deleteProjectFromSupabase(id);
      setProjects(prev => prev.filter(p => p.id !== id));
    } catch (err: any) {
      console.error('UI Delete Error:', err);
      // Show error in the UI instead of alert
      setError('خطا در حذف پروژه: ' + (err.message || 'مشکلی پیش آمد'));
    } finally {
      setDeletingId(null);
    }
  };

  const handleLoad = (project: SavedProject) => {
    const content = project.content;
    const restoredItem: MediaItem = {
      ...content,
      id: project.id,
      file: null as any,
      isCloudRestored: true,
      fileName: content.fileName || 'پروژه ذخیره شده'
    };
    onLoadProject(restoredItem);
    onClose();
  };

  const requestSort = (key: SortKey) => {
    let direction: 'asc' | 'desc' = 'asc';
    if (sortConfig.key === key && sortConfig.direction === 'asc') {
      direction = 'desc';
    }
    setSortConfig({ key, direction });
  };

  const filteredAndSortedProjects = useMemo(() => {
    // 1. Filter
    let items = projects.filter(p => {
      const name = p.content.fileName || 'بدون نام';
      return name.toLowerCase().includes(searchTerm.toLowerCase());
    });

    // 2. Sort
    items.sort((a, b) => {
      let aValue: any;
      let bValue: any;

      if (sortConfig.key === 'fileName') {
        aValue = a.content.fileName || '';
        bValue = b.content.fileName || '';
      } else if (sortConfig.key === 'status') {
        aValue = a.content.status || '';
        bValue = b.content.status || '';
      } else {
        aValue = new Date(a.updated_at).getTime();
        bValue = new Date(b.updated_at).getTime();
      }

      if (aValue < bValue) {
        return sortConfig.direction === 'asc' ? -1 : 1;
      }
      if (aValue > bValue) {
        return sortConfig.direction === 'asc' ? 1 : -1;
      }
      return 0;
    });

    return items;
  }, [projects, searchTerm, sortConfig]);

  const SortIcon = ({ colKey }: { colKey: SortKey }) => {
    if (sortConfig.key !== colKey) return <ArrowUpDown size={14} className="text-slate-300" />;
    return sortConfig.direction === 'asc' 
      ? <ArrowUp size={14} className="text-indigo-600" /> 
      : <ArrowDown size={14} className="text-indigo-600" />;
  };

  if (!isOpen) return null;

  return (
    <>
      <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
        <div className="bg-white w-full max-w-5xl rounded-2xl shadow-2xl flex flex-col max-h-[85vh] overflow-hidden animate-in fade-in zoom-in-95 duration-200">
          
          {/* Header */}
          <div className="p-5 border-b border-slate-100 flex items-center justify-between bg-slate-50">
            <div>
              <h2 className="text-xl font-bold text-slate-800 flex items-center gap-2">
                <CloudDownload className="text-indigo-600" />
                کتابخانه پروژه‌ها
              </h2>
              <p className="text-xs text-slate-500 mt-1">مدیریت فایل‌های ذخیره شده در فضای ابری</p>
            </div>
            <button onClick={onClose} className="p-2 hover:bg-slate-200 rounded-full transition-colors text-slate-500">
              <X size={24} />
            </button>
          </div>

          {/* Toolbar */}
          <div className="p-4 border-b border-slate-100 flex gap-4 bg-white items-center">
            <div className="relative flex-1 max-w-md">
              <Search className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
              <input 
                type="text" 
                placeholder="جستجو در نام فایل‌ها..." 
                className="w-full pl-4 pr-10 py-2 rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500 text-sm"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
              />
            </div>
            <div className="flex-1"></div>
            <button 
              onClick={fetchProjects} 
              className="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-600 rounded-lg text-sm font-medium transition"
            >
              بروزرسانی
            </button>
          </div>

          {/* Table Content */}
          <div className="flex-1 overflow-y-auto bg-slate-50/50">
            {loading ? (
              <div className="flex flex-col items-center justify-center h-64 text-slate-400 gap-3">
                <Loader2 className="animate-spin text-indigo-500" size={32} />
                <span>در حال دریافت اطلاعات...</span>
              </div>
            ) : error ? (
              <div className="flex flex-col items-center justify-center h-64 text-red-500 gap-3 bg-red-50 m-4 rounded-xl border border-red-100">
                <AlertCircle size={32} />
                <span>{error}</span>
              </div>
            ) : filteredAndSortedProjects.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-64 text-slate-400 gap-3 border-2 border-dashed border-slate-200 m-4 rounded-xl">
                <FileAudio size={48} className="text-slate-300" />
                <span>هیچ پروژه‌ای یافت نشد.</span>
              </div>
            ) : (
              <table className="w-full text-right border-collapse">
                <thead className="bg-slate-100 sticky top-0 z-10 text-xs font-semibold text-slate-600 shadow-sm">
                  <tr>
                    <th 
                      className="p-4 cursor-pointer hover:bg-slate-200 transition-colors group" 
                      onClick={() => requestSort('fileName')}
                    >
                      <div className="flex items-center gap-2">
                        نام فایل
                        <SortIcon colKey="fileName" />
                      </div>
                    </th>
                    <th 
                      className="p-4 cursor-pointer hover:bg-slate-200 transition-colors group w-48" 
                      onClick={() => requestSort('updated_at')}
                    >
                      <div className="flex items-center gap-2">
                        تاریخ آخرین تغییر
                        <SortIcon colKey="updated_at" />
                      </div>
                    </th>
                    <th 
                      className="p-4 cursor-pointer hover:bg-slate-200 transition-colors group w-40" 
                      onClick={() => requestSort('status')}
                    >
                      <div className="flex items-center gap-2">
                        وضعیت
                        <SortIcon colKey="status" />
                      </div>
                    </th>
                    <th className="p-4 w-24 text-center">عملیات</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 bg-white">
                  {filteredAndSortedProjects.map((project) => {
                    const meta = project.content;
                    const lastVer = meta.versions && meta.versions.length > 0 
                        ? meta.versions[meta.versions.length - 1] 
                        : null;
                    
                    return (
                      <tr 
                        key={project.id} 
                        onClick={() => handleLoad(project)}
                        className="hover:bg-indigo-50 cursor-pointer transition-colors group relative"
                      >
                        <td className="p-4">
                          <div className="flex items-center gap-3">
                              <div className="bg-slate-100 text-indigo-600 p-2 rounded-lg shrink-0">
                                <FileAudio size={20} />
                              </div>
                              <div className="min-w-0">
                                <div className="font-bold text-slate-700 text-sm truncate max-w-xs md:max-w-sm lg:max-w-md" title={meta.fileName}>
                                    {meta.fileName || 'بدون نام'}
                                </div>
                                {lastVer && (
                                  <div className="text-[10px] text-slate-400 mt-0.5 truncate max-w-xs">
                                    آخرین نسخه: {lastVer.name}
                                  </div>
                                )}
                              </div>
                          </div>
                        </td>
                        <td className="p-4">
                          <div className="flex flex-col gap-0.5 text-xs text-slate-500">
                              <div className="flex items-center gap-1.5">
                                <Calendar size={12} />
                                <span>{new Date(project.updated_at).toLocaleDateString('fa-IR')}</span>
                              </div>
                              <div className="flex items-center gap-1.5">
                                <Clock size={12} />
                                <span>{new Date(project.updated_at).toLocaleTimeString('fa-IR')}</span>
                              </div>
                          </div>
                        </td>
                        <td className="p-4">
                          <div className="flex items-center gap-2">
                            <span className={`w-2 h-2 rounded-full ${meta.status === 'completed' ? 'bg-green-500' : meta.status === 'processing' ? 'bg-amber-500' : 'bg-slate-300'}`}></span>
                            <span className="text-xs text-slate-600">
                              {meta.status === 'completed' ? 'تکمیل شده' : meta.status === 'processing' ? 'در حال پردازش' : 'پیش‌نویس'}
                            </span>
                          </div>
                        </td>
                        <td className="p-4 text-center relative">
                          <button 
                              type="button"
                              onClick={(e) => promptDelete(project.id, e)}
                              className="relative z-20 p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition"
                              title="حذف پروژه"
                            >
                              {deletingId === project.id ? <Loader2 className="animate-spin" size={18} /> : <Trash2 size={18} />}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
          
          {/* Footer info */}
          <div className="p-3 border-t border-slate-100 bg-slate-50 text-[10px] text-slate-400 text-center">
            نمایش {filteredAndSortedProjects.length} پروژه
          </div>
        </div>
      </div>

      {/* Custom Confirmation Modal */}
      {deleteConfirmation.isOpen && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-white rounded-xl shadow-2xl max-w-sm w-full p-6 scale-100 animate-in zoom-in-95 duration-200">
            <div className="flex flex-col items-center text-center gap-4">
              <div className="w-12 h-12 rounded-full bg-red-100 text-red-600 flex items-center justify-center ring-4 ring-red-50">
                <AlertTriangle size={24} />
              </div>
              <div>
                <h3 className="text-lg font-bold text-slate-800">حذف پروژه</h3>
                <p className="text-sm text-slate-500 mt-2">
                  آیا از حذف این پروژه مطمئن هستید؟ این عملیات غیرقابل بازگشت است و تمام نسخه‌های ذخیره شده پاک خواهند شد.
                </p>
              </div>
              <div className="flex gap-3 w-full mt-4">
                <button 
                  onClick={() => setDeleteConfirmation({ isOpen: false, id: null })}
                  className="flex-1 px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg font-medium transition"
                >
                  انصراف
                </button>
                <button 
                  onClick={performDelete}
                  className="flex-1 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg font-medium transition shadow-lg shadow-red-200 flex items-center justify-center gap-2"
                >
                  <Trash2 size={16} />
                  <span>حذف کن</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default FileManager;