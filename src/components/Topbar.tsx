interface TopbarProps {
  accepted: boolean
  rootBalance: number
  onBrandClick: () => void
}

export function Topbar({ accepted, rootBalance, onBrandClick }: TopbarProps) {
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
        <div className="topbar-session">
          <div className="status">
            <span className="status-dot" />
            КОНТУР АКТИВЕН
          </div>
          <div className="topbar-wallet" aria-label={`Баланс ROOT: ${rootBalance}`}>
            <span>ROOT</span>
            <strong>{rootBalance}</strong>
          </div>
        </div>
      )}
    </header>
  )
}
