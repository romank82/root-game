interface TopbarProps {
  accepted: boolean
  onBrandClick: () => void
}

export function Topbar({ accepted, onBrandClick }: TopbarProps) {
  return (
    <header className="topbar">
      <button
        className="brand"
        onClick={() => {
          if (accepted) {
            onBrandClick()
          }
        }}
      >
        <span className="brand-mark">◈</span>
        <span>
          <strong>CHIMERA</strong>
          <small>PROTOCOL // 01</small>
        </span>
      </button>

      {accepted && (
        <div className="status">
          <span className="status-dot" />
          КОНТУР АКТИВЕН
        </div>
      )}
    </header>
  )
}
