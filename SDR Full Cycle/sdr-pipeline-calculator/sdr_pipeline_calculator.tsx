<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Pipeline Calculator</title>

  <!-- Fonts -->
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  
  <!-- Tailwind CSS -->
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      theme: {
        extend: {
          fontFamily: { sans: ['Inter', 'sans-serif'] },
        }
      }
    }
  </script>

  <!-- React & ReactDOM -->
  <script src="https://unpkg.com/react@18/umd/react.production.min.js" crossorigin></script>
  <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js" crossorigin></script>
  
  <!-- Babel for in-browser JSX compilation -->
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
</head>
<body class="bg-[#FBFBFB] text-zinc-900 font-sans selection:bg-zinc-200">
  <div id="root"></div>

  <script type="text/babel">
    const { useState } = React;

    // SVG definitions for Lucide Icons
    const ICONS = {
      Calculator: '<rect width="16" height="20" x="4" y="2" rx="2"/><line x1="8" x2="16" y1="6" y2="6"/><line x1="16" x2="16" y1="14" y2="14"/><line x1="16" x2="16" y1="10" y2="10"/><line x1="16" x2="16" y1="18" y2="18"/><line x1="8" x2="8" y1="14" y2="14"/><line x1="8" x2="8" y1="10" y2="10"/><line x1="8" x2="8" y1="18" y2="18"/><line x1="12" x2="12" y1="14" y2="14"/><line x1="12" x2="12" y1="10" y2="10"/><line x1="12" x2="12" y1="18" y2="18"/>',
      TrendingUp: '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>',
      Users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
      Target: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
      ArrowUpRight: '<line x1="7" y1="17" x2="17" y2="7"/><polyline points="7 7 17 7 17 17"/>',
      Briefcase: '<rect width="20" height="14" x="2" y="7" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>',
      Layers: '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 12 12 17 22 12"/><polyline points="2 17 12 22 22 17"/>',
      Percent: '<line x1="19" x2="5" y1="5" y2="19"/><circle cx="6.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="17.5" r="2.5"/>',
      History: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
      Info: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
      CheckCircle: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>'
    };

    const Icon = ({ name, className }) => (
      <svg className={className} xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" dangerouslySetInnerHTML={{ __html: ICONS[name] }} />
    );

    function App() {
      const [sdrCount, setSdrCount] = useState(5);
      const [targetRevenue, setTargetRevenue] = useState(150000);
      const [multiplier, setMultiplier] = useState(3);
      const [asp, setAsp] = useState(34000); // Updated default ASP to 34,000
      const [qualRate, setQualRate] = useState(24);
      const [lastYearMeetings, setLastYearMeetings] = useState(248);

      const formatCurrency = (val) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(val);
      const formatNum = (val) => new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(val);

      const dealsWon = asp > 0 ? targetRevenue / asp : 0;
      const pipelineDeals = dealsWon * multiplier;
      const pipelineRevenue = targetRevenue * multiplier;
      
      // Math.ceil ensures we always round up to a whole meeting
      const meetingsPerSdr = qualRate > 0 ? Math.ceil(pipelineDeals / (qualRate / 100)) : 0;
      const totalMeetings = meetingsPerSdr * sdrCount;
      
      const increaseNeeded = totalMeetings - lastYearMeetings;
      const pctIncrease = lastYearMeetings > 0 ? ((totalMeetings / lastYearMeetings) - 1) * 100 : 0;
      
      // Changed boolean to strictly check if we need MORE meetings
      const isPositiveGap = increaseNeeded > 0;

      return (
        <div className="p-4 md:p-8 lg:p-12">
          <div className="max-w-6xl mx-auto space-y-8">
            
            <header className="pb-6 border-b border-zinc-200">
              <div className="flex items-center gap-3 mb-2">
                <div className="p-2 bg-white border border-zinc-200 rounded-md shadow-sm">
                  <Icon name="Calculator" className="w-5 h-5 text-zinc-800" />
                </div>
                <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">Pipeline Calculator</h1>
              </div>
              <p className="text-zinc-500 text-sm">Reverse-engineer meeting requirements based on revenue targets.</p>
            </header>

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-12">
              
              {/* Controls Column */}
              <section className="lg:col-span-4 space-y-6">
                <div className="flex items-center justify-between pb-2 border-b border-zinc-100">
                  <h2 className="text-sm font-medium text-zinc-800">Variables</h2>
                </div>
                
                <div className="space-y-5">
                  <InputRow icon="Users" label="Number of SDRs" value={sdrCount} setter={setSdrCount} step="1" />
                  <InputRow icon="Target" label="Target Revenue per SDR ($)" value={targetRevenue} setter={setTargetRevenue} step="1000" />
                  <InputRow icon="Layers" label="Pipeline Multiplier (x)" value={multiplier} setter={setMultiplier} step="0.5" />
                  <InputRow icon="Briefcase" label="Average Selling Price ($)" value={asp} setter={setAsp} step="100" />
                  <InputRow icon="Percent" label="Qualification Rate (%)" value={qualRate} setter={setQualRate} step="1" />
                  <InputRow 
                    icon="History" 
                    label="Last Year's Meetings" 
                    value={lastYearMeetings} 
                    setter={setLastYearMeetings} 
                    step="10" 
                    tooltip="eng group size between 1-101, created in the last 365d, deal owner is known"
                  />
                </div>
              </section>

              {/* Outputs Column */}
              <section className="lg:col-span-8 flex flex-col space-y-8">
                
                <div className="bg-zinc-900 text-white rounded-xl p-8 shadow-sm border border-zinc-800 relative overflow-hidden">
                  <div className="absolute top-0 right-0 p-8 opacity-10 pointer-events-none">
                    <Icon name="TrendingUp" className="w-48 h-48" />
                  </div>
                  <div className="relative z-10">
                    <h3 className="text-zinc-400 text-sm font-medium mb-4 flex items-center gap-2">
                      Target Delta
                    </h3>
                    
                    {/* Dynamic Header State */}
                    {isPositiveGap ? (
                      <>
                        <div className="flex items-end gap-4 mb-2">
                          <div className="text-5xl md:text-6xl font-semibold tracking-tight">
                            +{formatNum(increaseNeeded)}
                          </div>
                          <div className="flex items-center gap-1 text-lg mb-2 px-2 py-1 rounded-md font-medium bg-zinc-800 text-zinc-100">
                            <Icon name="ArrowUpRight" className="w-5 h-5" />
                            {formatNum(pctIncrease)}%
                          </div>
                        </div>
                        <p className="text-zinc-400 text-sm max-w-md leading-relaxed mt-4">
                          To hit the new targets, the team must generate <strong className="text-zinc-200">{formatNum(increaseNeeded)}</strong> more meetings compared to last year's baseline of {lastYearMeetings}.
                        </p>
                      </>
                    ) : (
                      <>
                        <div className="flex items-end gap-4 mb-2">
                          <div className="text-4xl md:text-5xl font-semibold tracking-tight text-emerald-400 flex items-center gap-3">
                            <Icon name="CheckCircle" className="w-10 h-10" /> 
                            Target Covered
                          </div>
                        </div>
                        <p className="text-emerald-500/80 text-sm max-w-md leading-relaxed mt-4">
                          You have enough meetings. Last year's baseline of <strong className="text-emerald-400">{lastYearMeetings}</strong> is sufficient to reach the required <strong className="text-emerald-400">{formatNum(totalMeetings)}</strong> meetings.
                        </p>
                      </>
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <MetricCard label="Total Meetings" value={formatNum(totalMeetings)} />
                  <MetricCard label="Meetings per SDR" value={formatNum(meetingsPerSdr)} />
                  <MetricCard label="Pipeline Deals" value={formatNum(pipelineDeals)} />
                  <MetricCard label="Deals Won (SDR)" value={formatNum(dealsWon)} />
                </div>

                <div className="bg-white border border-zinc-200 rounded-xl overflow-hidden shadow-sm">
                  <div className="px-6 py-4 border-b border-zinc-100 bg-zinc-50/50">
                    <h3 className="text-sm font-medium text-zinc-800 flex items-center gap-2">
                      Formula Breakdown
                    </h3>
                  </div>
                  <div className="p-6 text-sm text-zinc-600 font-mono space-y-4 overflow-x-auto">
                    <FormulaRow step="1" title="Deals Won Needed" formula="Target Revenue / ASP" calc={`${formatCurrency(targetRevenue)} / ${formatCurrency(asp)}`} result={formatNum(dealsWon)} />
                    <FormulaRow step="2" title="Pipeline Deals" formula="Deals Won * Multiplier" calc={`${formatNum(dealsWon)} * ${multiplier}`} result={formatNum(pipelineDeals)} />
                    <FormulaRow step="3" title="Pipeline Revenue" formula="Target Revenue * Multiplier" calc={`${formatCurrency(targetRevenue)} * ${multiplier}`} result={formatCurrency(pipelineRevenue)} />
                    <FormulaRow step="4" title="Meetings (per SDR)" formula="Math.ceil(Pipeline Deals / Qual Rate)" calc={`${formatNum(pipelineDeals)} / ${qualRate}%`} result={formatNum(meetingsPerSdr)} />
                    <FormulaRow step="5" title="Total Team Meetings" formula="Meetings per SDR * SDRs" calc={`${formatNum(meetingsPerSdr)} * ${sdrCount}`} result={formatNum(totalMeetings)} />
                    <div className="pt-3 border-t border-zinc-100">
                      <FormulaRow 
                        step="6" 
                        title="Meeting Delta" 
                        formula="Total Meetings - Baseline" 
                        calc={`${formatNum(totalMeetings)} - ${lastYearMeetings}`} 
                        result={isPositiveGap ? `+${formatNum(increaseNeeded)}` : 'Target Met'} 
                        highlight={isPositiveGap}
                        success={!isPositiveGap} 
                      />
                    </div>
                  </div>
                </div>

              </section>
            </div>
          </div>
        </div>
      );
    }

    function InputRow({ icon, label, value, setter, step, tooltip }) {
      return (
        <div>
          <label className="flex items-center gap-2 text-sm font-medium text-zinc-600 mb-1.5 relative group w-fit cursor-default">
            <span className="flex items-center gap-2">
              <span className="text-zinc-400"><Icon name={icon} className="w-4 h-4" /></span>
              {label}
            </span>
            {tooltip && (
              <div className="relative flex items-center">
                <Icon name="Info" className="w-4 h-4 text-zinc-400 hover:text-zinc-600 transition-colors" />
                <div className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 hidden group-hover:block w-48 p-2.5 bg-zinc-800 text-zinc-100 text-xs font-normal rounded-md shadow-lg z-50 text-center pointer-events-none leading-relaxed">
                  {tooltip}
                  <div className="absolute left-1/2 -translate-x-1/2 top-full w-0 h-0 border-l-[5px] border-r-[5px] border-t-[5px] border-l-transparent border-r-transparent border-t-zinc-800"></div>
                </div>
              </div>
            )}
          </label>
          <input 
            type="number" 
            step={step}
            value={value} 
            onChange={(e) => setter(Number(e.target.value))} 
            className="w-full px-3 py-2 bg-white border border-zinc-200 rounded-lg text-sm text-zinc-900 shadow-sm focus:border-zinc-500 focus:ring-1 focus:ring-zinc-500 transition-all outline-none" 
          />
        </div>
      );
    }

    function MetricCard({ label, value }) {
      return (
        <div className="bg-white p-5 rounded-xl border border-zinc-200 shadow-sm flex flex-col justify-between">
          <span className="text-xs font-medium text-zinc-500 mb-2">{label}</span>
          <span className="text-2xl font-semibold tracking-tight text-zinc-900">{value}</span>
        </div>
      );
    }

    function FormulaRow({ step, title, formula, calc, result, highlight = false, success = false }) {
      return (
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 py-1">
          <div className="flex items-center gap-3 min-w-[240px]">
            <span className="text-zinc-400 select-none">{step}.</span>
            <span className="font-medium text-zinc-700">{title}</span>
          </div>
          <div className="hidden sm:block text-zinc-400 text-xs truncate flex-1 px-4">
            {formula}
          </div>
          <div className="flex items-center gap-3 text-right">
            <span className="text-zinc-400 text-xs hidden md:inline-block">{calc}</span>
            <span className="text-zinc-300 hidden md:inline-block">=</span>
            <span className={`font-semibold ${success ? 'text-emerald-500' : (highlight ? 'text-zinc-900' : 'text-zinc-700')}`}>{result}</span>
          </div>
        </div>
      );
    }

    const root = ReactDOM.createRoot(document.getElementById('root'));
    root.render(<App />);
  </script>
</body>
</html>