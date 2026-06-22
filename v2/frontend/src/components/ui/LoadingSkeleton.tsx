import React from 'react';

interface LoadingSkeletonProps {
  rows?: number;
  height?: string;
  width?: string;
  className?: string;
}

const shimmerKeyframes = `
@keyframes shimmer {
  0% { background-position: -600px 0; }
  100% { background-position: 600px 0; }
}
`;

let styleInjected = false;
function injectShimmerStyle() {
  if (styleInjected || typeof document === 'undefined') return;
  const style = document.createElement('style');
  style.textContent = shimmerKeyframes;
  document.head.appendChild(style);
  styleInjected = true;
}

export const LoadingSkeleton: React.FC<LoadingSkeletonProps> = ({
  rows = 3,
  height = '16px',
  width = '100%',
  className,
}) => {
  if (typeof document !== 'undefined') injectShimmerStyle();

  const shimmerStyle: React.CSSProperties = {
    background:
      'linear-gradient(90deg, var(--bg-panel) 0%, var(--bg-elevated) 40%, var(--bg-hover) 60%, var(--bg-panel) 100%)',
    backgroundSize: '600px 100%',
    animation: 'shimmer 1.4s ease-in-out infinite',
    borderRadius: 'var(--radius-sm)',
    height,
    width,
  };

  return (
    <div
      data-testid="loading-skeleton"
      className={className}
      style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}
      aria-busy="true"
      aria-label="Loading..."
    >
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          style={{
            ...shimmerStyle,
            // Vary widths slightly for a more natural look
            width: i === rows - 1 && rows > 1 ? '70%' : width,
          }}
        />
      ))}
    </div>
  );
};

export default LoadingSkeleton;
