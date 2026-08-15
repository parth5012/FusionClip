'use client';

import React, { useState, useEffect, useRef } from 'react';
import { 
  Folder, File, Upload, Trash2, Plus, Play, RefreshCw, 
  ChevronRight, Volume2, Video as VideoIcon, Image as ImageIcon,
  Loader2, Cpu, ArrowLeft, ArrowUpRight, CheckCircle2, AlertCircle
} from 'lucide-react';
import { 
  fetchFiles, uploadFile, deleteFile, createFolder, 
  startTask, getTaskStatus, StorageItem, TaskStatusResponse 
} from '../utils/api';
import { useStore } from '../store/useStore';

export default function FileManager() {
  const { setActiveTab, setUpscaleTarget } = useStore();
  const [currentDir, setCurrentDir] = useState<string>('');
  const [directories, setDirectories] = useState<StorageItem[]>([]);
  const [files, setFiles] = useState<StorageItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Folder inputs
  const [newFolderName, setNewFolderName] = useState<string>('');
  const [creatingFolder, setCreatingFolder] = useState<boolean>(false);

  // File upload
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState<boolean>(false);

  // Active Celery tasks monitoring
  const [activeTasks, setActiveTasks] = useState<Record<string, {
    id: string;
    objectName: string;
    taskType: string;
    state: string;
    percent?: number;
    statusText?: string;
  }>>({});

  const loadDirectory = async (dir: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchFiles(dir);
      setCurrentDir(data.current_dir);
      setDirectories(data.directories);
      setFiles(data.files);
    } catch (err: any) {
      setError(err.message || 'Failed to populate files list.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDirectory('');
  }, []);

  // Poll celery task statuses
  useEffect(() => {
    const taskIds = Object.keys(activeTasks).filter(
      id => activeTasks[id].state === 'PENDING' || activeTasks[id].state === 'PROGRESS'
    );

    if (taskIds.length === 0) return;

    const interval = setInterval(async () => {
      for (const id of taskIds) {
        try {
          const status: TaskStatusResponse = await getTaskStatus(id);
          
          setActiveTasks(prev => {
            const currentTask = prev[id];
            if (!currentTask) return prev;

            let updatedTask = { ...currentTask, state: status.state };

            if (status.state === 'PROGRESS' && status.info) {
              updatedTask.percent = status.info.percent;
              updatedTask.statusText = status.info.status;
            } else if (status.state === 'SUCCESS') {
              updatedTask.percent = 100;
              updatedTask.statusText = 'Completed processing task!';
              // Reload directory to show the newly generated output file!
              loadDirectory(currentDir);
            } else if (status.state === 'FAILURE') {
              updatedTask.statusText = `Error: ${status.info}`;
            }

            return { ...prev, [id]: updatedTask };
          });
        } catch (taskErr) {
          console.error('Polling task error: ', taskErr);
        }
      }
    }, 1500);

    return () => clearInterval(interval);
  }, [activeTasks, currentDir]);

  // Navigate folder level
  const handleFolderClick = (dirPath: string) => {
    loadDirectory(dirPath);
  };

  const handleGoBack = () => {
    const segments = currentDir.replace(/\/$/, '').split('/');
    segments.pop();
    const parentPath = segments.length > 0 ? segments.join('/') + '/' : '';
    loadDirectory(parentPath);
  };

  // Breadcrumbs utils
  const getBreadcrumbs = () => {
    const list = [{ name: 'Root', path: '' }];
    if (!currentDir) return list;
    
    const parts = currentDir.replace(/\/$/, '').split('/');
    let accum = '';
    parts.forEach(part => {
      accum += part + '/';
      list.push({ name: part, path: accum });
    });
    return list;
  };

  // Delete handler
  const handleDelete = async (filePath: string) => {
    if (!confirm(`Are you sure you want to delete ${filePath}?`)) return;
    try {
      await deleteFile(filePath);
      loadDirectory(currentDir);
    } catch (err: any) {
      alert(err.message || 'Failed to delete file');
    }
  };

  // Create folder
  const handleCreateFolder = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newFolderName.trim()) return;
    setCreatingFolder(true);
    
    // Construct absolute target key virtual location prefix
    const path = currentDir ? `${currentDir}${newFolderName}` : newFolderName;
    try {
      await createFolder(path);
      setNewFolderName('');
      loadDirectory(currentDir);
    } catch (err: any) {
      alert(err.message || 'Failed to create folder');
    } finally {
      setCreatingFolder(false);
    }
  };

  // Upload handler
  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const filesList = e.target.files;
    if (!filesList || filesList.length === 0) return;
    
    setUploading(true);
    try {
      await uploadFile(filesList[0], currentDir);
      loadDirectory(currentDir);
    } catch (err: any) {
      alert(err.message || 'Failed to upload selected file');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  // Trigger Celery Task
  const handleTriggerTask = async (filePath: string, taskType: string) => {
    try {
      const taskRes = await startTask(filePath, taskType);
      setActiveTasks(prev => ({
        ...prev,
        [taskRes.task_id]: {
          id: taskRes.task_id,
          objectName: filePath,
          taskType: taskType,
          state: taskRes.status
        }
      }));
    } catch (err: any) {
      alert(err.message || 'Pipeline dispatch failed');
    }
  };

  // Help format filesizes
  const formatSize = (bytes?: number) => {
    if (bytes === undefined || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  // Detect file categories for icons or previewing
  const getFileIcon = (fileName: string) => {
    const ext = fileName.split('.').pop()?.toLowerCase();
    if (['png', 'jpg', 'jpeg', 'svg', 'webp', 'gif'].includes(ext || '')) {
      return <ImageIcon className="w-5 h-5 text-emerald-400" />;
    }
    if (['mp4', 'mov', 'webm', 'ogg', 'mkv'].includes(ext || '')) {
      return <VideoIcon className="w-5 h-5 text-indigo-400" />;
    }
    if (['mp3', 'wav', 'aac', 'flac'].includes(ext || '')) {
      return <Volume2 className="w-5 h-5 text-amber-400" />;
    }
    return <File className="w-5 h-5 text-slate-400" />;
  };

  return (
    <div className="space-y-6">
      {/* Active Jobs panel */}
      {Object.keys(activeTasks).length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-5">
          <h3 className="font-semibold text-slate-200 mb-3 flex items-center gap-2">
            <Cpu className="w-4 h-4 text-sky-400 animate-pulse" />
            Background Task Engine Tasks (Celery Status)
          </h3>
          <div className="space-y-3">
            {Object.values(activeTasks).map(task => (
              <div key={task.id} className="bg-slate-950 p-3 rounded border border-slate-900 text-sm">
                <div className="flex justify-between items-center mb-1">
                  <span className="font-medium text-slate-300">
                    {task.taskType.toUpperCase()}: <span className="text-slate-400 text-xs font-mono">{task.objectName}</span>
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded font-mono ${
                    task.state === 'SUCCESS' ? 'bg-emerald-950 text-emerald-400' :
                    task.state === 'FAILURE' ? 'bg-rose-950 text-rose-400' :
                    'bg-sky-950 text-sky-400 animate-pulse'
                  }`}>
                    {task.state}
                  </span>
                </div>
                
                {task.state !== 'SUCCESS' && task.state !== 'FAILURE' && (
                  <div className="mt-2 w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                    <div 
                      className="bg-sky-500 h-full transition-all duration-300"
                      style={{ width: `${task.percent || 10}%` }}
                    />
                  </div>
                )}
                
                {task.statusText && (
                  <p className="text-xs text-slate-400 mt-1 flex items-center gap-1">
                    {task.state === 'SUCCESS' ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> :
                     task.state === 'FAILURE' ? <AlertCircle className="w-3.5 h-3.5 text-rose-400" /> :
                     <Loader2 className="w-3.5 h-3.5 animate-spin text-sky-400" />}
                    {task.statusText}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Directory operations toolbar */}
      <div className="flex flex-col sm:flex-row gap-4 justify-between items-start sm:items-center bg-slate-900 border border-slate-800 p-4 rounded-lg">
        {/* Navigation Breadcrumbs */}
        <div className="flex items-center gap-1 overflow-x-auto py-1 max-w-full">
          {currentDir && (
            <button 
              onClick={handleGoBack}
              className="mr-2 p-1.5 hover:bg-slate-800 rounded text-slate-400 transition"
              title="Go back a level"
            >
              <ArrowLeft className="w-4 h-4" />
            </button>
          )}

          {getBreadcrumbs().map((b, idx) => (
            <React.Fragment key={b.path}>
              {idx > 0 && <ChevronRight className="w-3 h-3 text-slate-600 flex-shrink-0" />}
              <button
                onClick={() => handleFolderClick(b.path)}
                className={`text-sm px-2 py-1 rounded transition whitespace-nowrap hover:bg-slate-800 ${
                  idx === getBreadcrumbs().length - 1 ? 'text-sky-400 font-semibold bg-slate-950/40 border border-slate-800' : 'text-slate-400'
                }`}
              >
                {b.name}
              </button>
            </React.Fragment>
          ))}
        </div>

        {/* Action inputs */}
        <div className="flex flex-wrap items-center gap-3 w-full sm:w-auto">
          {/* Create folder */}
          <form onSubmit={handleCreateFolder} className="flex gap-2">
            <input
              type="text"
              placeholder="New folder name..."
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              className="bg-slate-950 border border-slate-700 px-3 py-1.5 rounded text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-sky-500 focus:border-sky-500 w-36 sm:w-44"
            />
            <button
              type="submit"
              disabled={creatingFolder || !newFolderName}
              className="bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-200 px-3 py-1.5 rounded text-sm transition flex items-center gap-1.5 border border-slate-700"
            >
              {creatingFolder ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
              Folder
            </button>
          </form>

          {/* Upload File */}
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white px-4 py-1.5 rounded text-sm transition flex items-center gap-1.5 font-medium ml-auto sm:ml-0"
          >
            {uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
            Upload file
          </button>
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleUpload}
            className="hidden"
          />
          
          <button
            onClick={() => loadDirectory(currentDir)}
            className="p-2 border border-slate-700 rounded text-slate-400 hover:bg-slate-800 transition"
            title="Refresh current folder"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Main Filesystem View */}
      {loading ? (
        <div className="flex flex-col items-center justify-center py-20 bg-slate-900/50 border border-slate-800/80 rounded-lg">
          <Loader2 className="w-8 h-8 animate-spin text-sky-500" />
          <p className="text-slate-400 text-sm mt-3">Syncing with MinIO S3 storage buckets...</p>
        </div>
      ) : error ? (
        <div className="bg-rose-950/20 border border-rose-800/80 rounded-lg p-6 text-center text-rose-300">
          <p className="font-semibold text-lg">Communication error</p>
          <p className="text-sm opacity-90 mt-1">{error}</p>
          <button 
            onClick={() => loadDirectory(currentDir)}
            className="mt-4 px-4 py-1.5 bg-rose-900/50 hover:bg-rose-900 border border-rose-700 text-slate-200 rounded text-sm transition"
          >
            Retry connection
          </button>
        </div>
      ) : directories.length === 0 && files.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 bg-slate-900/40 border border-slate-800/60 border-dashed rounded-lg text-slate-500">
          <Folder className="w-12 h-12 stroke-[1] text-slate-600 mb-2" />
          <p className="text-sm font-medium">Empty bucket path</p>
          <p className="text-xs opacity-75 mt-1">Upload a file or create folders to get started.</p>
        </div>
      ) : (
        <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
          <div className="grid grid-cols-1 divide-y divide-slate-800">
            {/* Headers (desktop) */}
            <div className="hidden md:grid grid-cols-12 gap-4 px-6 py-3 bg-slate-950 text-xs font-semibold text-slate-400 uppercase tracking-wider">
              <div className="col-span-6">Name</div>
              <div className="col-span-2">Size</div>
              <div className="col-span-4 text-right">Actions</div>
            </div>

            {/* Folder rows */}
            {directories.map(dir => (
              <div 
                key={dir.path} 
                className="grid grid-cols-1 md:grid-cols-12 items-center gap-4 px-6 py-3.5 hover:bg-slate-850 transition cursor-pointer text-sm"
                onClick={() => handleFolderClick(dir.path)}
              >
                <div className="col-span-6 flex items-center gap-3">
                  <div className="p-1.5 bg-slate-950 rounded text-sky-400">
                    <Folder className="w-5 h-5 fill-current" />
                  </div>
                  <span className="font-medium text-slate-200 hover:text-sky-400 transition">{dir.name}</span>
                </div>
                <div className="col-span-2 text-slate-500 text-xs">— (Directory)</div>
                <div className="col-span-4 flex justify-end">
                  <span className="text-xs text-sky-400/70 border border-sky-950 bg-sky-950/20 px-2 py-0.5 rounded md:block hidden">Browse Folder</span>
                </div>
              </div>
            ))}

            {/* File rows */}
            {files.map(file => (
              <div 
                key={file.path} 
                className="grid grid-cols-1 md:grid-cols-12 items-center gap-4 px-6 py-3.5 hover:bg-slate-850/50 transition text-sm"
              >
                {/* File Title */}
                <div className="col-span-6 flex items-center gap-3">
                  <div className="p-1.5 bg-slate-950 rounded">
                    {getFileIcon(file.name)}
                  </div>
                  <div className="truncate max-w-[85%]">
                    <p className="font-medium text-slate-300 truncate" title={file.name}>{file.name}</p>
                    <p className="text-[10px] text-slate-500 font-mono truncate">{file.path}</p>
                  </div>
                </div>

                {/* Size / Metadata */}
                <div className="col-span-2 text-slate-400 text-xs">
                  {formatSize(file.size)}
                </div>

                {/* File Actions */}
                <div className="col-span-4 flex items-center justify-end gap-2.5">
                  {/* Task launch dropdown/triggers */}
                  <div className="flex items-center gap-1.5 border border-slate-700 bg-slate-950/60 p-1 rounded-md">
                    <button
                      onClick={() => handleTriggerTask(file.path, 'transcode')}
                      className="text-xs hover:bg-slate-800 text-slate-300 hover:text-sky-400 p-1 px-1.5 rounded transition flex items-center gap-1"
                      title="Transcode video/audio via Celery worker"
                    >
                      <Play className="w-3 h-3 text-sky-500" /> Transcode
                    </button>
                    <div className="w-[1px] h-3.5 bg-slate-850" />
                    <button
                      onClick={() => {
                        // Open the dedicated Upscaler panel with this file
                        // preselected (map #57/#59 controls live there).
                        setUpscaleTarget(file.path);
                        setActiveTab('upscaler');
                      }}
                      className="text-xs hover:bg-slate-800 text-slate-300 hover:text-emerald-400 p-1 px-1.5 rounded transition flex items-center gap-1"
                      title="Upscale file resolution"
                    >
                      <Cpu className="w-3 h-3 text-emerald-500" /> Upscale
                    </button>
                  </div>

                  {/* Playback / Pre-signed direct link */}
                  {file.url && (
                    <a 
                      href={file.url} 
                      target="_blank" 
                      rel="noopener noreferrer" 
                      className="p-1.5 bg-slate-800 border border-slate-700 rounded text-slate-300 hover:bg-slate-700 hover:text-white transition"
                      title="Open file URL directly"
                    >
                      <ArrowUpRight className="w-4 h-4" />
                    </a>
                  )}

                  {/* Delete file */}
                  <button
                    onClick={() => handleDelete(file.path)}
                    className="p-1.5 bg-slate-950/80 hover:bg-rose-950/60 border border-slate-855 text-slate-400 hover:text-rose-400 rounded transition"
                    title="Delete object"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
