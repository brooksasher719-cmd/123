import { createClient } from '@supabase/supabase-js';
import { MediaItem } from '../types';

const SUPABASE_URL = 'https://qmxagajsdncdquloxdtd.supabase.co';
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFteGFnYWpzZG5jZHF1bG94ZHRkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjY1MzYxMzAsImV4cCI6MjA4MjExMjEzMH0.q17TSNbjzN8_QSfa7mmmto7StE1EUaiOeUlA4e_NUNM';

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

export interface SavedProject {
  id: string;
  content: any; // Storing the serializable part of MediaItem
  updated_at: string;
}

// Prepare item for saving (remove File object)
const serializeItem = (item: MediaItem) => {
  const { file, ...rest } = item;
  return {
    ...rest,
    fileName: file ? file.name : (item as any).fileName || 'بدون نام',
    fileSize: file ? file.size : (item as any).fileSize || 0,
    fileType: file ? file.type : (item as any).fileType || 'audio/mp3',
    savedAt: new Date().toISOString()
  };
};

export const saveProjectToSupabase = async (item: MediaItem) => {
  const serialized = serializeItem(item);
  
  const { data, error } = await supabase
    .from('transcriptions')
    .upsert({
      id: item.id,
      content: serialized,
      updated_at: new Date().toISOString()
    })
    .select();

  if (error) throw error;
  return data;
};

export const loadProjectsFromSupabase = async (): Promise<SavedProject[]> => {
  const { data, error } = await supabase
    .from('transcriptions')
    .select('*')
    .order('updated_at', { ascending: false });

  if (error) throw error;
  return data || [];
};

export const deleteProjectFromSupabase = async (id: string) => {
  console.log('--- DELETE PROCESS STARTED ---');
  console.log('Target ID:', id);

  // 1. First, check if the item ACTUALLY exists and is visible
  const check = await supabase
    .from('transcriptions')
    .select('id')
    .eq('id', id)
    .single();

  if (check.error) {
    console.error('Check Existence Error:', check.error);
    throw new Error('فایل مورد نظر در دیتابیس یافت نشد یا دسترسی خواندن ندارید.');
  }

  console.log('Item found, proceeding to delete...');

  // 2. Attempt to delete
  const { error, count } = await supabase
    .from('transcriptions')
    .delete({ count: 'exact' })
    .eq('id', id);

  if (error) {
    console.error('Delete Error:', error);
    throw new Error(error.message);
  }

  console.log('Delete Count Result:', count);

  // If count is 0, it means RLS blocked it, because we proved it exists in step 1
  if (count === 0 || count === null) {
    throw new Error('دیتابیس عملیات حذف را مسدود کرد! (RLS Error). لطفاً دستور SQL "DISABLE ROW LEVEL SECURITY" را در سوپابیس اجرا کنید.');
  }
  
  return true;
};