import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './App.css'

const slideMeta = [
  'Cover',
  'Problem',
  'Market',
  'Solution',
  'Intelligence',
  'Demo',
  'Team',
  'Close',
]

const clampSlideIndex = (index) => Math.min(Math.max(index, 0), slideMeta.length - 1)

const team = [
  ['Arsénio Ferraz', 'team/arsenio.png', '1010137'],
  ['César Vieira', 'team/cesar.jpg', '1241523'],
  ['Rui Soares', 'team/rui.jpg', '1221283'],
  ['Gonçalo Jesus', 'team/goncalo.jpg', '1220822'],
  ['Rynalde Serejo', 'team/rynalde.jpg', '1252445'],
]

function Metric({ value, label, tone = 'neutral' }) {
  return (
    <div className={`metric metric-${tone}`}>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  )
}

function LogoLockup() {
  return (
    <div className="logo-lockup" aria-label="Team 10 Phish'N'Chips25 logo">
      <img className="logo-mark" src="team/logo.jpg" alt="Phish'N'Chips25 logo" />
      <span className="logo-badge logo-team">Phish&apos;N&apos;Chips25 · Team 10 · MEIA ISEP</span>
    </div>
  )
}

function OfficeMap() {
  const zones = [
    'work room 1',
    'work room 2',
    'work room 3',
    'work room 4',
    'datacenter',
    'lobby',
    'corridor',
    'break room',
  ]

  return (
    <div className="office-map" aria-label="SentinelMAS office floor plan">
      {zones.map((zone) => (
        <span key={zone} className={`zone zone-${zone.replaceAll(' ', '-')}`}>
          {zone}
        </span>
      ))}
      <span className="path path-one" />
      <span className="path path-two" />
      <span className="ppo-trace" />
      <span className="ppo-waypoint waypoint-one" />
      <span className="ppo-waypoint waypoint-two" />
      <span className="ppo-waypoint waypoint-three" />
      <span className="ppo-vector" />
      <div className="ppo-tracker" aria-hidden="true">
        <span className="ppo-chip">PPO tracking</span>
        <strong>waypoint 3/5 locked</strong>
        <em>vx 0.31 · vy 0.04 · yaw -0.12</em>
        <span className="ppo-bars"><span /><span /><span /></span>
      </div>
      <span className="robot-dot"><span /></span>
      <span className="intruder-dot"><span /></span>
    </div>
  )
}

function Pipeline() {
  const stages = [
    ['Perception', 'InsightFace', 'known vs intruder'],
    ['Decision', 'SIMAGIA SPADE', 'Contract Net auction'],
    ['Navigation', 'PPO + A*', 'wall-aware waypoints'],
    ['Actuation', 'Booster T1', 'Webots + ROS 2 RPC'],
  ]

  return (
    <div className="pipeline" aria-label="System pipeline">
      {stages.map(([title, tool, detail]) => (
        <div className="stage" key={title}>
          <span>{title}</span>
          <strong>{tool}</strong>
          <small>{detail}</small>
        </div>
      ))}
    </div>
  )
}

function VideoSlot({ label, fileName, caption }) {
  const [loaded, setLoaded] = useState(false)

  return (
    <div className="video-slot">
      <video
        aria-label={`${label} video`}
        controls
        playsInline
        preload="metadata"
        onLoadedData={() => setLoaded(true)}
        onError={() => setLoaded(false)}
      >
        <source src={`/videos/${fileName}`} type="video/mp4" />
      </video>
      {!loaded && (
        <div className="video-fallback" aria-hidden="true">
          <span className="video-mark" />
          <strong>{label}</strong>
          <span>{caption}</span>
        </div>
      )}
    </div>
  )
}

function NavigationChrome({ activeIndex, goTo, previousSlide, nextSlide }) {
  return (
    <>
      <div className="slide-progress" aria-label="Slide progress">
        {slideMeta.map((label, index) => (
          <button
            aria-label={`Go to ${label}`}
            className={index === activeIndex ? 'is-active' : ''}
            key={label}
            onClick={() => goTo(index)}
            type="button"
          />
        ))}
      </div>
      <div className="deck-controls">
        <button
          aria-label="Previous slide"
          className="control control-prev"
          disabled={activeIndex === 0}
          onClick={previousSlide}
          type="button"
        />
        <button
          aria-label="Next slide"
          className="control control-next"
          disabled={activeIndex === slideMeta.length - 1}
          onClick={nextSlide}
          type="button"
        />
      </div>
    </>
  )
}

function PitchDeck() {
  const deckRef = useRef(null)
  const [activeIndex, setActiveIndex] = useState(0)

  const goTo = useCallback((index) => {
    setActiveIndex(clampSlideIndex(index))
  }, [])

  const stepSlide = useCallback((delta) => {
    setActiveIndex((current) => clampSlideIndex(current + delta))
  }, [])

  const previousSlide = useCallback(() => {
    stepSlide(-1)
  }, [stepSlide])

  const nextSlide = useCallback(() => {
    stepSlide(1)
  }, [stepSlide])

  useEffect(() => {
    deckRef.current?.focus({ preventScroll: true })
  }, [])

  useEffect(() => {
    const onKeyDown = (event) => {
      const tagName = event.target.tagName.toLowerCase()

      if (tagName === 'video') {
        return
      }

      if (event.key === 'ArrowRight' || event.key === 'ArrowDown' || event.key === 'PageDown') {
        event.preventDefault()
        stepSlide(1)
      }

      if (event.key === 'ArrowLeft' || event.key === 'ArrowUp' || event.key === 'PageUp') {
        event.preventDefault()
        stepSlide(-1)
      }

      if (event.key === 'Home') {
        event.preventDefault()
        goTo(0)
      }

      if (event.key === 'End') {
        event.preventDefault()
        goTo(slideMeta.length - 1)
      }
    }

    window.addEventListener('keydown', onKeyDown)

    return () => window.removeEventListener('keydown', onKeyDown)
  }, [goTo, stepSlide])

  const transform = useMemo(() => ({ transform: `translate3d(-${activeIndex * 100}vw, 0, 0)` }), [activeIndex])
  const slideClass = (index, names) => `slide ${names} ${activeIndex === index ? 'is-current' : ''}`

  return (
    <main ref={deckRef} className="presentation" aria-label="SentinelMAS 5-minute pitch" tabIndex={0}>
      <header className="deck-header" aria-hidden="true">
        <span className="deck-header-brand">
          <img className="deck-header-logo" src="team/logo.jpg" alt="" />
          Phish&apos;N&apos;Chips25 · Team 10
        </span>
        <span className="deck-header-challenge">Challenge 4</span>
      </header>
      <div className="slides" style={transform}>
        {/* 1 — Cover */}
        <section className={slideClass(0, 'slide-hero')}>
          <div className="slide-inner hero-grid">
            <div className="hero-copy">
              <p className="eyebrow">MEIA ISEP · Challenge 4 · Team 10</p>
              <h1 className="hero-hook" aria-label="SentinelMAS">
                <span aria-hidden="true">SentinelMAS</span>
                <span aria-hidden="true">security that acts.</span>
              </h1>
              <p className="lede">
                One autonomous system that senses a threat, decides who responds,
                and sends a patrol robot to the right place.
              </p>
              <LogoLockup />
            </div>
            <div className="hero-visual">
              <OfficeMap />
            </div>
          </div>
        </section>

        {/* 2 — Problem */}
        <section className={slideClass(1, 'slide-light')}>
          <div className="slide-inner split-layout">
            <div>
              <p className="eyebrow">The problem</p>
              <h2>Cyber and physical alerts stay apart, so response is slow and blind.</h2>
              <p className="supporting">
                A cyber alert rarely knows who is standing in the room. A camera
                rarely knows a server is under attack. Teams lose the minutes that matter.
              </p>
            </div>
            <div className="proof-grid problem-grid">
              <Metric value="€9.7T" label="projected annual global cost of cybercrime (Cybersecurity Ventures, 2025)" tone="red" />
              <Metric value="€4.1M" label="average cost of a single data breach (IBM, 2025)" tone="blue" />
              <Metric value="~240 days" label="to detect and contain a breach (IBM, 2025)" tone="orange" />
              <Metric value="€120B+" label="global physical security market (2024)" tone="green" />
            </div>
          </div>
        </section>

        {/* 3 — Market */}
        <section className={slideClass(2, 'slide-dark')}>
          <div className="slide-inner elements-layout">
            <div>
              <p className="eyebrow">Who needs this</p>
              <h2>Any site where digital assets and physical access share a building.</h2>
            </div>
            <div className="element-grid market-grid">
              <div><strong>Data centers</strong><span>High-value racks needing combined cyber and access monitoring.</span></div>
              <div><strong>Corporate campuses</strong><span>Multi-zone offices with limited security staff after hours.</span></div>
              <div><strong>Critical infrastructure</strong><span>Energy, telecom and labs where intrusion has real-world impact.</span></div>
              <div><strong>SOC &amp; facility teams</strong><span>Operators who must triage many alerts with one response unit.</span></div>
              <div><strong>Security robotics providers</strong><span>Patrol-as-a-service vendors wanting smarter dispatch.</span></div>
              <div><strong>Smart buildings</strong><span>Sites already wired with cameras, PIR and network telemetry.</span></div>
            </div>
          </div>
        </section>

        {/* 4 — Solution (system + differentiator) */}
        <section className={slideClass(3, 'slide-light')}>
          <div className="slide-inner architecture-layout">
            <div>
              <p className="eyebrow">The solution</p>
              <h2>SentinelMAS decides. PPO drives. The robot acts.</h2>
              <p className="supporting">
                The differentiator: an auction-based multi-agent layer fuses cyber and
                physical evidence, then dispatches one robot to the highest-threat zone.
              </p>
            </div>
            <Pipeline />
            <div className="bridge-line">
              <span>Python · SPADE</span>
              <span>PPO · Stable-Baselines3</span>
              <span>A* planner</span>
              <span>ROS 2 · Webots · Booster T1</span>
            </div>
          </div>
        </section>

        {/* 5 — Intelligence / proof */}
        <section className={slideClass(4, 'slide-dark')}>
          <div className="slide-inner navigation-layout pitch-intel">
            <div>
              <p className="eyebrow">Why it is credible</p>
              <h2>Trained navigation that reaches every zone without hitting walls.</h2>
            </div>
            <div className="nav-visual">
              <OfficeMap />
              <div className="policy-panel">
                <span>Auction picks the zone by threat level</span>
                <span>A* plans wall-safe waypoints</span>
                <span>PPO outputs walk speed and turn rate</span>
              </div>
            </div>
            <div className="metrics-row">
              <Metric value="100%" label="zone arrival from random starts" tone="green" />
              <Metric value="0/56" label="wall-clearance failures" tone="blue" />
              <Metric value="0.39 m" label="minimum route clearance" tone="orange" />
            </div>
          </div>
        </section>

        {/* 6 — Demo */}
        <section className={slideClass(5, 'slide-light')}>
          <div className="slide-inner video-layout">
            <div>
              <p className="eyebrow">See it run</p>
              <h2>From a detected intruder to a robot on its way.</h2>
            </div>
            <div className="video-grid video-grid-single">
              <VideoSlot
                caption="Perception, threat fusion, auction, and Webots mission dispatch"
                fileName="recording.mp4"
                label="SentinelMAS run"
              />
            </div>
          </div>
        </section>

        {/* 7 — Team */}
        <section className={slideClass(6, 'slide-silver')}>
          <div className="slide-inner research-layout">
            <div>
              <p className="eyebrow">The team</p>
              <h2>Team 10 — Phish&apos;N&apos;Chips25, MEIA ISEP.</h2>
            </div>
            <div className="team-cards">
              {team.map(([name, photo, studentId]) => (
                <div className="team-card" key={name}>
                  <img className="avatar" src={photo} alt={name} />
                  <strong>{name}</strong>
                  <span className="team-skill">Nº {studentId}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* 8 — Close */}
        <section className={slideClass(7, 'slide-close')}>
          <div className="slide-inner close-layout">
            <p className="eyebrow">Team 10 / Challenge 4</p>
            <h2>We are Phish&apos;N&apos;Chips25.</h2>
            <p className="punchline">From scattered alerts to coordinated action.</p>
            <LogoLockup />
            <a className="blog-link" href="https://phish-n-chips25.github.io/blog/" target="_blank" rel="noreferrer">
              phish-n-chips25.github.io/blog
            </a>
          </div>
        </section>
      </div>

      <NavigationChrome
        activeIndex={activeIndex}
        goTo={goTo}
        nextSlide={nextSlide}
        previousSlide={previousSlide}
      />
    </main>
  )
}

export default PitchDeck
