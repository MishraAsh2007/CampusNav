/** Display-only outlines traced in the source image frame. Never routing geometry. */
export default function SimplifiedFloorPlan({plan}) {
  const labelStyle = {fontFamily: 'Inter, system-ui, sans-serif'};
  return <g aria-label="Simplified floor plan: classroom outlines, corridors and elevators">
    <rect x="300" y="300" width="900" height="800" fill="#f1f5f7" />
    <polygon points={plan.outline} fill="white" stroke="#64748b" strokeWidth="2.5" strokeLinejoin="round" />
    {plan.zones.map((z, i) => <g key={i}>
      <polygon points={z.points} fill={z.kind === 'void' ? '#e2e8f0' : z.kind === 'service' ? '#eef2f6' : '#f0fdfa'} stroke="#cbd5e1" strokeWidth="1.5" strokeDasharray={z.kind === 'void' ? '5 4' : undefined} />
      <text x={z.at[0]} y={z.at[1]} textAnchor="middle" fontSize={z.kind === 'service' ? '10' : '13'} fill="#64748b" style={labelStyle}>{z.label}</text>
      {z.subtitle && <text x={z.at[0]} y={z.at[1]+17} textAnchor="middle" fontSize="11" fill="#64748b" style={labelStyle}>{z.subtitle}</text>}
    </g>)}
    {plan.rooms.map(([label, points, at]) => {
      const [x,y] = at.split(',');
      return <g key={label}><title>{`${label}: approximate room outline from the published plan`}</title>
        <polygon points={points} fill="#e9eef3" stroke="#94a3b8" strokeWidth="1.8" strokeLinejoin="round" />
        <text x={x} y={y} fill="#334155" textAnchor="middle" fontSize={['S142','S112','S122','S242','S241A'].includes(label) ? 10 : 16} fontWeight="600" style={labelStyle}>{label}</text>
        {label === 'N151' && <text x={x} y={Number(y)+17} fill="#64748b" textAnchor="middle" fontSize="11" style={labelStyle}>Auditorium</text>}
      </g>;
    })}
    {plan.lifts.map(lift => <g key={lift.id}>
      <title>{lift.id === 'north' ? 'North elevator beside N155 / N255' : lift.id === 'east' ? 'North Pleasant Street elevator beside S110 / S220' : `Central elevator ${lift.id === 'central-q' ? 'Q' : 'P'}`}</title>
      <rect x={lift.x-9} y={lift.y-11} width="18" height="22" rx="3" fill="#6d28d9" stroke="white" strokeWidth="1.5" />
      <path d={`M${lift.x-4},${lift.y-2} l4,-5 4,5 Z M${lift.x-4},${lift.y+2} l4,5 4,-5 Z`} fill="white" />
    </g>)}
    <text x="563" y="346" fontSize="13" fontWeight="600" textAnchor="middle" fill="#6d28d9" style={labelStyle}>North elevator</text>
    <path d={`M541 353 L${plan.lifts[0].x} ${plan.lifts[0].y-15}`} fill="none" stroke="#a78bfa" strokeWidth="1.3" />
    <text x="732" y="800" fontSize="12" fontWeight="600" textAnchor="middle" fill="#6d28d9" style={labelStyle}>2 elevators</text>
    {plan.lifts.some(lift => lift.id === 'east') && <text x="1105" y="818" fontSize="11" fontWeight="600" textAnchor="middle" fill="#6d28d9" style={labelStyle}>East elevator</text>}
    <g>
      <path d={`M${plan.entrance.x-10},${plan.entrance.y+3} l20,-6`} stroke="#0284c7" strokeWidth="6" strokeLinecap="round" />
      <path d={`M${plan.entrance.label[0]},${plan.entrance.label[1]+8} L${plan.entrance.x},${plan.entrance.y}`} stroke="#0284c7" strokeWidth="1.3" fill="none" />
      <text x={plan.entrance.label[0]} y={plan.entrance.label[1]} textAnchor="middle" fontSize="14" fontWeight="600" fill="#0369a1" style={labelStyle}>{plan.entrance.text}</text>
    </g>
  </g>;
}
