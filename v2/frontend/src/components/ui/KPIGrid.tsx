import React from 'react';

interface KPIGridProps {
  children: React.ReactNode;
  columns?: number | 'auto';
  className?: string;
}

export const KPIGrid: React.FC<KPIGridProps> = ({ children, columns = 'auto', className }) => {
  const gridTemplateColumns =
    columns === 'auto'
      ? 'repeat(auto-fill, minmax(200px, 1fr))'
      : `repeat(${columns}, 1fr)`;

  return (
    <div
      data-testid="kpi-grid"
      className={className}
      style={{
        display: 'grid',
        gridTemplateColumns,
        gap: '12px',
        width: '100%',
      }}
    >
      {children}
    </div>
  );
};

export default KPIGrid;
