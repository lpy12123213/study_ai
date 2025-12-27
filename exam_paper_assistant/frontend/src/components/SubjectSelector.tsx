import { useState, useEffect, useRef } from 'react';
import { ChevronDown, GraduationCap, Check } from 'lucide-react';
import { getSubjects, type Subject } from '@/api';

interface Props {
  value: string;
  onChange: (subject: string) => void;
}

// 学段分组
const EDU_GROUPS = [
  { id: 3, name: '高中', color: 'text-blue-400' },
  { id: 2, name: '初中', color: 'text-green-400' },
  { id: 1, name: '小学', color: 'text-orange-400' },
];

export default function SubjectSelector({ value, onChange }: Props) {
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadSubjects();
  }, []);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const loadSubjects = async () => {
    try {
      const data = await getSubjects();
      setSubjects(data);
    } catch (error) {
      console.error('Failed to load subjects:', error);
      // 使用默认学科列表
      setSubjects([
        { name: '高中数学', short_name: '数学', bank_id: 11, edu_id: 3 },
        { name: '高中语文', short_name: '语文', bank_id: 10, edu_id: 3 },
        { name: '高中英语', short_name: '英语', bank_id: 12, edu_id: 3 },
        { name: '高中物理', short_name: '物理', bank_id: 13, edu_id: 3 },
        { name: '高中化学', short_name: '化学', bank_id: 14, edu_id: 3 },
        { name: '高中生物', short_name: '生物', bank_id: 15, edu_id: 3 },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const currentSubject = subjects.find(s => s.name === value);
  const groupedSubjects = EDU_GROUPS.map(group => ({
    ...group,
    subjects: subjects.filter(s => s.edu_id === group.id)
  })).filter(g => g.subjects.length > 0);

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-3 py-1.5 bg-slate-800/50 hover:bg-slate-700/50 rounded-lg border border-white/10 transition-all"
        disabled={loading}
      >
        <GraduationCap className="w-4 h-4 text-primary" />
        <span className="text-sm text-white font-medium">
          {loading ? '加载中...' : (currentSubject?.name || value)}
        </span>
        <ChevronDown className={`w-4 h-4 text-slate-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <div className="absolute top-full right-0 mt-2 w-64 glass rounded-xl shadow-2xl shadow-black/50 z-50 overflow-hidden animate-fade-in origin-top-right">
          <div className="p-2 border-b border-white/5 bg-white/5">
            <div className="text-xs text-slate-400 px-2 font-medium">选择学科</div>
          </div>
          <div className="max-h-80 overflow-y-auto custom-scrollbar">
            {groupedSubjects.map(group => (
              <div key={group.id}>
                <div className={`px-3 py-2 text-xs font-bold ${group.color} bg-slate-950/30 sticky top-0 backdrop-blur-sm`}>
                  {group.name}
                </div>
                <div className="py-1">
                  {group.subjects.map(subject => (
                    <button
                      key={subject.name}
                      onClick={() => {
                        onChange(subject.name);
                        setIsOpen(false);
                      }}
                      className={`w-full px-3 py-2 flex items-center justify-between hover:bg-white/5 transition-colors group ${value === subject.name ? 'bg-primary/10' : ''
                        }`}
                    >
                      <span className={`text-sm transition-colors ${value === subject.name ? 'text-primary font-medium' : 'text-slate-300 group-hover:text-white'
                        }`}>
                        {subject.short_name}
                      </span>
                      {value === subject.name && (
                        <Check className="w-4 h-4 text-primary" />
                      )}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
