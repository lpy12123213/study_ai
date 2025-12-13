import { Radar, RadarChart, PolarGrid, PolarAngleAxis, ResponsiveContainer } from 'recharts';
import { Brain, Gauge, Activity } from 'lucide-react';

interface AnalysisProps {
  analysis: {
    difficulty_score: number;
    radar_data: Array<{ subject: string; A: number; fullMark: number }>;
    ai_comment: string;
  };
}

export default function AnalysisCard({ analysis }: AnalysisProps) {
  if (!analysis) return null;

  // Convert score to percentage for progress bar
  const diffPercent = Math.round(analysis.difficulty_score * 100);
  let diffColor = 'bg-green-500';
  if (diffPercent > 40) diffColor = 'bg-yellow-500';
  if (diffPercent > 70) diffColor = 'bg-red-500';

  return (
    <div className="bg-slate-900/50 border border-primary/20 rounded-xl p-4 mb-4 space-y-4">
      <div className="flex items-center gap-2 text-primary font-semibold">
        <Brain className="w-5 h-5" />
        AI 试卷分析
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        {/* Left: Stats */}
        <div className="space-y-4">
          <div>
            <div className="flex justify-between text-xs text-slate-400 mb-1">
              <span className="flex items-center gap-1"><Gauge className="w-3 h-3" /> 难度系数</span>
              <span>{analysis.difficulty_score} / 1.0</span>
            </div>
            <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
              <div 
                className={`h-full ${diffColor} transition-all duration-500`} 
                style={{ width: `${diffPercent}%` }}
              />
            </div>
          </div>
          
          <div className="bg-slate-800/50 p-3 rounded-lg border border-white/5">
            <div className="flex items-start gap-2">
              <Activity className="w-4 h-4 text-primary mt-0.5 shrink-0" />
              <p className="text-sm text-slate-300 leading-relaxed">
                {analysis.ai_comment}
              </p>
            </div>
          </div>
        </div>

        {/* Right: Chart */}
        <div className="h-[200px] w-full relative">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart cx="50%" cy="50%" outerRadius="70%" data={analysis.radar_data}>
                <PolarGrid stroke="rgba(255,255,255,0.1)" />
                <PolarAngleAxis dataKey="subject" tick={{ fill: '#94a3b8', fontSize: 12 }} />
                <Radar
                  name="题型分布"
                  dataKey="A"
                  stroke="#32d5c4"
                  fill="#32d5c4"
                  fillOpacity={0.4}
                />
              </RadarChart>
            </ResponsiveContainer>
            <div className="absolute bottom-0 right-0 text-[10px] text-slate-600">Distribution</div>
        </div>
      </div>
    </div>
  );
}
