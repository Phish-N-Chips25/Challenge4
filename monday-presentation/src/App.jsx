import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './App.css'

const slideMeta = [
  'Opening',
  'Problem',
  'Timeline',
  'Architecture',
  'Elements',
  'Decision model',
  'Navigation',
  'Demo',
  'Status',
  'Close',
]

const clampSlideIndex = (index) => Math.min(Math.max(index, 0), slideMeta.length - 1)

function Metric({ value, label, tone = 'neutral' }) {
  return (
    <div className={`metric metric-${tone}`}>
      <strong>{value}</strong>
      <span>{label}</span>
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

function RLTrainingViz() {
  return (
    <div className="rl-lab" aria-label="PPO reinforcement learning loop animation">
      <div className="rl-loop">
        <span className="rl-node rl-observe">observe</span>
        <span className="rl-node rl-policy">PPO policy</span>
        <span className="rl-node rl-action">action</span>
        <span className="rl-node rl-reward">reward</span>
        <span className="rl-pulse" />
      </div>
      <div className="rl-episodes" aria-hidden="true">
        <span /><span /><span /><span /><span /><span /><span /><span />
      </div>
      <div className="reward-chart" aria-hidden="true">
        <span className="reward-line reward-line-one" />
        <span className="reward-line reward-line-two" />
        <span className="reward-line reward-line-three" />
        <span className="reward-line reward-line-four" />
        <span className="reward-dot" />
      </div>
      <div className="rl-caption">
        <strong>learning signal</strong>
        <span>reward improves as unsafe turns disappear</span>
      </div>
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

function App() {
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
    <main ref={deckRef} className="presentation" aria-label="SentinelMAS pitch deck" tabIndex={0}>
      <header className="deck-header" aria-hidden="true">
        <span className="deck-header-brand">
          <img className="deck-header-logo" src="team/logo.jpg" alt="" />
          Phish&apos;N&apos;Chips25 · Team 10
        </span>
        <span className="deck-header-challenge">Challenge 4</span>
      </header>
      <div className="slides" style={transform}>
        <section className={slideClass(0, 'slide-hero')}>
          <div className="slide-inner hero-grid">
            <div className="hero-copy">
              <p className="eyebrow">SentinelMAS / Challenge 4</p>
              <h1 className="hero-hook" aria-label="A cyber alert is only half the story.">
                <span aria-hidden="true">A cyber alert</span>
                <span aria-hidden="true">is only half the story.</span>
              </h1>
              <p className="lede">
                Who is standing in the room? Our system connects endpoint telemetry,
                face recognition, multi-agent reasoning, and robot patrol into one response.
              </p>
            </div>
            <div className="hero-visual">
              <OfficeMap />
            </div>
          </div>
        </section>

        <section className={slideClass(1, 'slide-light')}>
          <div className="slide-inner split-layout">
            <div>
              <p className="eyebrow">The problem</p>
              <h2>Security teams lose time when physical and digital signals live apart.</h2>
            </div>
            <div className="quiet-stack">
              <div className="insight-row">
                <span>01</span>
                <strong>Access control sees an unknown face.</strong>
                <p>Useful alone, but incomplete without context from the rest of the building.</p>
              </div>
              <div className="insight-row">
                <span>02</span>
                <strong>Cyber telemetry flags suspicious activity.</strong>
                <p>Urgency depends on whether someone is physically near the affected zone.</p>
              </div>
              <div className="insight-row">
                <span>03</span>
                <strong>One patrol robot must serve every zone.</strong>
                <p>The system needs prioritization, not first-come dispatch.</p>
              </div>
            </div>
          </div>
        </section>

        <section className={slideClass(2, 'slide-silver')}>
          <div className="slide-inner research-layout timeline-combined">
            <div>
              <p className="eyebrow">June build · July hardening</p>
              <h2>Four June weeks built the pipeline; July hardened it into a complete system.</h2>
            </div>
            <div className="timeline-grid">
              <div><span>Week 1</span><strong>RL foundation</strong><p>Docker/Python setup, PPO training config, and first patrol environment.</p></div>
              <div><span>Week 2</span><strong>MAS + Webots</strong><p>SIMAGIA agents, Contract Net auctions, the office world, and Booster T1 assets.</p></div>
              <div><span>Week 3</span><strong>Policy validated</strong><p>First office PPO baseline, used to harden route safety.</p></div>
              <div><span>Week 4</span><strong>Final integration</strong><p>Face ID, threat fusion, PPO navigation, JSONL missions, ROS 2, and Webots.</p></div>
            </div>
            <p className="eyebrow july-label">July · Delivered</p>
            <div className="ask-grid">
              <div><strong>Booster locomotion</strong><span>Integrated the Booster T1 stack with full locomotion and ran the complete patrol loop in Webots.</span></div>
              <div><strong>System integrated &amp; tested</strong><span>Validated simultaneous cyber and physical alerts, multiple intruders, and auction load end to end.</span></div>
              <div><strong>Documented &amp; reported</strong><span>Final report, architecture docs, and setup guides completed for handoff and deployment.</span></div>
            </div>
          </div>
        </section>

        <section className={slideClass(3, 'slide-light')}>
          <div className="slide-inner architecture-layout">
            <div>
              <p className="eyebrow">Architecture</p>
              <h2>SIMAGIA decides. PPO drives. Booster acts.</h2>
            </div>
            <Pipeline />
            <p className="eyebrow bridge-label">The Python bridges that connect these layers</p>
            <div className="bridge-line">
              <span>face_bridge.py</span>
              <span>nav_bridge.py</span>
              <span>booster_mission_bridge.py</span>
              <span>ppo_patrol_node.py</span>
            </div>
          </div>
        </section>

        <section className={slideClass(4, 'slide-dark')}>
          <div className="slide-inner elements-layout">
            <div>
              <p className="eyebrow">What each element did</p>
              <h2>The challenge worked because each component had a precise job.</h2>
            </div>
            <div className="element-grid">
              <div><strong>MotionAgent</strong><span>Converted physical presence into zone beliefs and corridor loitering signals.</span></div>
              <div><strong>FaceIDAgent</strong><span>Ran InsightFace/open-set identity checks: known staff stay low risk, unknown faces escalate.</span></div>
              <div><strong>CyberSentinel</strong><span>Injected cyber anomalies into the same zone model used by physical sensors.</span></div>
              <div><strong>Threat fusion</strong><span>Interpreted evidence by room capability: camera, cyber assets, motion, or all three.</span></div>
              <div><strong>ZoneCoordinator</strong><span>Held BDI beliefs, generated desires, selected plans, and bid for patrol.</span></div>
              <div><strong>PatrolAgent</strong><span>Ran the Contract Net auction and sent the robot to the highest-threat zone.</span></div>
              <div><strong>PPO + A*</strong><span>Turned a selected zone into wall-safe waypoints and velocity commands.</span></div>
              <div><strong>Booster bridge</strong><span>Sent missions through JSONL and mirrored robot status/pose back to SIMAGIA.</span></div>
            </div>
          </div>
        </section>

        <section className={slideClass(5, 'slide-silver')}>
          <div className="slide-inner split-layout decision-layout">
            <div>
              <p className="eyebrow">The differentiator</p>
              <h2>Auction-based response makes one robot behave like a coordinated team.</h2>
              <p className="supporting">
                Every ZoneCoordinator bids by threat level. Datacenter CRITICAL beats
                work-room HIGH, and losing zones stay eligible for the next auction.
              </p>
            </div>
            <div className="auction-board">
              <div className="bid bid-critical"><span>datacenter</span><strong>CRITICAL</strong></div>
              <div className="bid bid-high"><span>work_room_1</span><strong>HIGH</strong></div>
              <div className="bid bid-medium"><span>corridor</span><strong>MEDIUM</strong></div>
              <div className="winner"><span>winner</span><strong>dispatch patrol</strong></div>
            </div>
          </div>
        </section>

        <section className={slideClass(6, 'slide-dark')}>
          <div className="slide-inner navigation-layout">
            <div>
              <p className="eyebrow">Navigation</p>
              <h2>PPO handles movement while A* keeps the route wall-safe.</h2>
            </div>
            <div className="nav-visual">
              <OfficeMap />
              <div className="policy-panel">
                <span>Input: 8 sensor values per step</span>
                <span>Output: walk speed and turn rate</span>
                <span>Closed loop on the robot's real position</span>
                <RLTrainingViz />
              </div>
            </div>
            <div className="metrics-row">
              <Metric value="100%" label="zone arrival from random starts" tone="green" />
              <Metric value="0/56" label="wall-clearance failures" tone="blue" />
              <Metric value="0.39 m" label="minimum route clearance" tone="orange" />
            </div>
          </div>
        </section>

        <section className={slideClass(7, 'slide-light')}>
          <div className="slide-inner video-layout">
            <div>
              <p className="eyebrow">Demo · recorded run</p>
              <h2>One recorded run: decision layer, navigation, and the robot.</h2>
            </div>
            <div className="video-grid video-grid-single">
              <VideoSlot
                caption="Perception, threat fusion, auction, PPO navigation, and Webots mission dispatch"
                fileName="recording.mp4"
                label="SentinelMAS run"
              />
            </div>
          </div>
        </section>

        <section className={slideClass(8, 'slide-silver')}>
          <div className="slide-inner proof-layout">
            <div>
              <p className="eyebrow">What we validated</p>
              <h2>The full loop runs end to end — perception, decision, navigation, and a walking robot.</h2>
              <p className="supporting">Honest scope: detaining a moving target still uses the lidar planner, the whole system runs in Webots simulation, and it coordinates a single patrol robot over a curated face set.</p>
            </div>
            <div className="proof-grid">
              <Metric value="0.82+" label="known staff face scores" tone="green" />
              <Metric value="<0.11" label="intruder face scores" tone="red" />
              <Metric value="0.65" label="recognition threshold" tone="blue" />
              <Metric value="8" label="shared office zones" tone="orange" />
            </div>
            <div className="status-strip">
              <span>Software pipeline: working</span>
              <span>Face bridge: verified</span>
              <span>PPO + A*: validated</span>
              <span>Booster: walking in Webots</span>
            </div>
          </div>
        </section>

        <section className={slideClass(9, 'slide-close')}>
          <div className="slide-inner close-layout worked-layout final-team-layout">
            <p className="eyebrow">Team 10 / Challenge 4</p>
            <h2>From scattered alerts to coordinated robot response.</h2>
            <div className="worked-grid final-team-grid">
              <div><strong>Arsénio Ferraz</strong><p>Nº 1010137</p></div>
              <div><strong>César Vieira</strong><p>Nº 1241523</p></div>
              <div><strong>Rui Soares</strong><p>Nº 1221283</p></div>
              <div><strong>Gonçalo Jesus</strong><p>Nº 1220822</p></div>
              <div><strong>Rynalde Serejo</strong><p>Nº 1252445</p></div>
            </div>
            <p className="punchline">Perception decides the threat. SIMAGIA chooses the mission. PPO drives the response.</p>
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

export default App
