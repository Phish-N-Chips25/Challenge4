# SentinelMAS — SPADE Agent Skeleton

Esqueleto multi-agente standalone (sem Webots/ROS2) para perceber o fluxo de mensagens e o ciclo BDI antes da integração.

## Correr

```bash
pip install spade        # >= 4.1 (inclui servidor XMPP embebido, pyjabber)
python main.py
```

Não precisa de Prosody/ejabberd — o SPADE 4 arranca um servidor XMPP embebido (`embedded_xmpp_server=True`).

## Arquitetura → código

| Agente | Tipo (Wooldridge) | Ficheiro |
|---|---|---|
| ZoneCoordinatorAgent ×5 | Deliberativo (BDI) | `agents/zone_coordinator.py` |
| PatrolAgent | Híbrido (vertical layered): BDI dispatch + RL nav | `agents/patrol.py` |
| MotionAgent | Reativo | `agents/reactive_agents.py` |
| FaceIDAgent | Reativo | `agents/reactive_agents.py` |
| CyberSentinelAgent | Reativo | `agents/reactive_agents.py` |
| StaffRequestAgent | Reativo | `agents/reactive_agents.py` |
| AlertAgent | Reativo (sink) | `agents/reactive_agents.py` |

## Ciclo BDI (ZoneCoordinator)

1. **Belief revision** — `PerceptionListener` (CyclicBehaviour) ingere INFORMs dos agentes reativos e atualiza a `BeliefBase`
2. **Threat fusion** — correlação cyber × físico no `BDIDeliberationCycle` (PeriodicBehaviour, 2s):
   - cyber sem presença física → HIGH (intrusão remota)
   - cyber + cara desconhecida → CRITICAL
   - só cara desconhecida ou só cyber → MEDIUM
3. **Desire generation** — `utils/bdi.py::generate_desires`
4. **Plan selection** — `PlanLibrary.select`: trigger ∧ context, ordenado por utilidade (condições lógicas + pesos, sem ML)
5. **Intention execution** — corpo do plano envia mensagens FIPA-ACL

## FIPA-ACL

Performativas usadas: `inform` (eventos sensoriais, relatórios), `request` (dispatch de patrulha, reverificação), `agree`/`refuse` (aceitação/recusa de patrulha), `failure` (navegação falhada). Construção centralizada em `utils/messaging.py` com ontologia `sentinel-mas` e payload JSON.

## Pontos de integração futura

- `agents/patrol.py::NavigationStub` → substituir por política PPO (stable-baselines3) a publicar Twist em `/cmd_vel` via `bridges.ROS2Bridge`
- `agents/reactive_agents.py::Simulated*Sensor` → substituir pelos adaptadores reais (YOLOv8→InsightFace→liveness, DualSentinel)
- `bridges/__init__.py` → implementar `ROS2Bridge` e `WebotsBridge` (contrato: agentes nunca importam rclpy diretamente)
- `config/settings.py::ROS2_ENABLED` → flag de transição

## Cenário-chave demonstrado

```
CyberSentinel: anomalia no server_room (sem presença física)
  → ZC: threat=HIGH → desire dispatch_patrol → plan selecionado
  → REQUEST patrol_zone → Patrol: AGREE → en_route → scan
  → INFORM patrol_report(clear) → ZC: de-escalação para LOW
```
