import './App.css'

function Landing() {
  return (
    <main className="landing">
      <div className="landing-card">
        <img className="landing-logo" src="team/logo.jpg" alt="Phish'N'Chips25 logo" />
        <p className="landing-team-no">Team 10</p>
        <h1 className="landing-title">Phish&apos;N&apos;Chips25</h1>
        <p className="landing-challenge">Challenge 4 · SentinelMAS</p>
        <p className="landing-sub">MEIA · ISEP</p>
        <div className="landing-actions">
          <a className="landing-btn landing-btn-primary" href="?deck=demo">
            Demo Day
          </a>
          <a className="landing-btn landing-btn-ghost" href="?deck=pitch">
            Pitch (5 min)
          </a>
        </div>
      </div>
    </main>
  )
}

export default Landing
