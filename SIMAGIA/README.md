# SentinelMAS

Sistema multi-agente (MAS) de segurança para uma instalação dividida em zonas.
Combina três arquiteturas de agente segundo a taxonomia de Wooldridge:

| Arquitetura | Agentes | Papel |
|-------------|---------|-------|
| **Deliberativa (BDI)** | `ZoneCoordinator` (1 por zona) | Revisão de crenças → desejos → seleção de plano (por utilidade) → intenção; licita pela patrulha no leilão |
| **Híbrida (camadas)** | `Patrol` | Camada alta: leiloeiro Contract Net + execução de missão; camada baixa: navegação (stub RL/ROS2) |
| **Reativa** | `Motion`, `FaceID`, `CyberSentinel`, `StaffRequest`, `Alert` | Estímulo → resposta, sem deliberação |

Comunicação entre agentes via **XMPP** (SPADE 4) com mensagens **FIPA-ACL**
(`inform`, `request`, `cfp`, `propose`, `accept-proposal`, `reject-proposal`) e
payload JSON. A patrulha (robô único) é alocada por **negociação Contract Net**
entre os coordenadores — ver secção dedicada abaixo.

---

## Arquitetura em resumo

```
  Sensores (reativos)              Coordenadores (BDI)            Atuação
 ┌───────────────────┐         ┌───────────────────────┐
 │ MotionAgent       │─inform─▶│                       │◀─cfp/accept─┐
 │ FaceIDAgent       │─inform─▶│  ZoneCoordinator      │─propose────▶ PatrolAgent
 │ CyberSentinelAgent│─inform─▶│  (1 por zona)         │  (leilão)    (navega + inspeciona)
 └───────────────────┘         │                       │─inform─────▶ AlertAgent
                               │  fusão de ameaça      │              (operador humano)
   StaffRequestAgent ─inform──▶│  (por zona)           │
                               └───────────────────────┘
```

As 8 zonas: `lobby`, `break_room`, `corridor`, `work_room_1`, `work_room_2`, `work_room_3`, `work_room_4`, `datacenter`.

---

## Instalação

Já existe um ambiente virtual em `.venv`. Se precisares de o recriar:

```powershell
cd D:\PyCharmProjects\SIMAGIA\sentinel_mas
python -m venv .venv
.\.venv\Scripts\activate
pip install -r sentinel_mas\requirements.txt
```

> **Nota Windows:** as portas XMPP padrão (5222/5269) caem num intervalo
> reservado pelo Hyper-V neste sistema, por isso o projeto usa **5322/5326**
> (configurado em [`config/settings.py`](sentinel_mas/config/settings.py)).
> O servidor XMPP é embutido (pyjabber) — não precisas de servidor externo.

---

## Como correr

Todos os comandos são executados a partir da pasta interna do código:

```powershell
.\.venv\Scripts\activate
cd sentinel_mas
```

### Caso 0 — Dashboard web (recomendado, sem terminal)

```powershell
$env:SENTINEL_SIM="0"        # opcional: sem eventos aleatórios
python main.py --web
```

Abre **http://localhost:8080** no browser. Vês:
- uma **planta 2D vista de cima** com as 8 salas (coloridas pelo nível de ameaça)
  e o **robô de patrulha a deslocar-se** entre elas (base → zona → inspeciona →
  regressa), com a fase atual (`traveling`/`scanning`/`returning`);
- um **cartão por zona** (ameaça, interpretação, crenças ativas) com botões para
  injetar os eventos `1`-`6` e os cenários `a`-`e` com o rato;
- o estado do robô e do último leilão, e uma **timeline ao vivo**.

Corre tudo dentro do processo do MAS — a injeção é em memória, sem segundo
cliente XMPP. A velocidade do robô e o tempo de inspeção são ajustáveis em
[`settings.py`](sentinel_mas/config/settings.py) (`PATROL_SPEED`,
`PATROL_SCAN_SECONDS`); o layout da planta em `ZONE_POS`.

### Caso 1 — Execução simples (um terminal)

```powershell
python main.py
```

Arranca o servidor XMPP + os agentes. Os sensores reativos geram eventos
**simulados** aleatoriamente, por isso vês o sistema a reagir sozinho.
`Ctrl+C` para parar.

### Caso 2 — Execução com cores (um terminal, recomendado para demos)

```powershell
python run_color.py
```

Igual ao `main.py` mas com output colorido por tipo de agente (ciano =
coordenadores BDI, amarelo = patrulha, vermelho = alertas, etc.). É um simples
wrapper de visualização — não altera a lógica.

### Caso 3 — Acionar eventos manualmente (modo interativo, um terminal)

Para *perceberes* o sistema e disparares tu próprio as situações, em vez de
esperar pelos sensores aleatórios:

```powershell
$env:SENTINEL_SIM="0"          # opcional: desliga os eventos aleatórios
python main.py --interactive
```

Arranca o MAS **e** um menu de injeção de eventos no mesmo terminal. Escolhes o
evento (número) e a zona, e o injetor envia um `inform` ao coordenador dessa
zona — exatamente como faria um sensor real. A reação BDI aparece logo a seguir,
no mesmo terminal.

Com `SENTINEL_SIM=0` o terminal fica quieto entre os teus eventos, por isso vês
cada cenário isolado e limpo.

> **Porque um só terminal e não dois?** O servidor XMPP embutido do SPADE
> (pyjabber) não aceita de forma fiável um segundo processo cliente a ligar-se
> depois do arranque. O injetor corre **dentro** do processo do MAS, partilhando
> o mesmo container — o envio é em memória, sem rede, e nunca falha a ligação.

---

## Lógica de fusão de ameaça (por zona)

A fusão é **sensível à zona** — cada zona tem as suas modalidades de sensor e a
sua interpretação das evidências. Implementada em
[`threat_fusion.py`](sentinel_mas/agents/threat_fusion.py); modalidades por zona em
[`settings.py`](sentinel_mas/config/settings.py) (`ZONE_MODALITIES`).

| Zona | Modalidades | Evidência | Nível | Interpretação |
|------|-------------|-----------|-------|---------------|
| **datacenter** | motion, camera, cyber | cyber + motion + rosto desconhecido | `CRITICAL` | correlated critical incident |
| | | cyber + motion (sem face autorizada) | `CRITICAL` | unidentified presence during anomaly |
| | | cyber + face autorizada | `LOW` | benign admin activity |
| | | cyber só (sem presença) | `HIGH` | remote attack |
| | | motion + rosto desconhecido | `HIGH` | physical intruder |
| **lobby** | motion, camera | motion + rosto desconhecido | `HIGH` | visual intruder |
| | | motion + face autorizada | `LOW` | authorized presence |
| | | motion só | `MEDIUM` | unidentified presence |
| **break_room** | motion, camera | motion + rosto desconhecido | `HIGH` | visual intruder |
| | | motion + face autorizada | `LOW` | authorized presence |
| | | motion só | `MEDIUM` | unidentified presence |
| **work_room_1–4** | motion, cyber | cyber + motion | `HIGH` | presence correlated w/ anomaly (patrulha p/ ID) |
| | (sem camera) | cyber só | `HIGH` | compromised workstation |
| | | motion só | `MEDIUM` | unidentified presence (sem camera) |
| **corridor** | motion | motion sustentado (≥3) | `MEDIUM` | suspicious loitering |
| | | motion pontual | `LOW` | transit |

Bursts de eventos correlacionados são fundidos **atomicamente**: a deliberação
espera ~0.4s após a última perceção, para ver o conjunto completo em vez de
reagir a cada evento isolado.

E os planos disponíveis (selecionados por utilidade, o mais alto ganha):

| Plano | Dispara quando | Utilidade | Ação |
|-------|----------------|-----------|------|
| `verify_identity` | rosto desconhecido, sem cyber, ameaça < HIGH | 5 | pede recaptura ao FaceID |
| `raise_alert` | ameaça ≥ CRITICAL | 20 | notifica operador humano |

> A patrulha **não** é um plano direto — é alocada por negociação (ver abaixo).
> Quando a ameaça ≥ HIGH, o coordenador anuncia interesse e licita no leilão.

---

## Negociação entre coordenadores (Contract Net Protocol)

Há **um só robô de patrulha** para 8 zonas — um recurso escasso. Quando várias
zonas o querem ao mesmo tempo, ele é alocado por **leilão** (FIPA Contract Net),
em vez de "quem pede primeiro ganha". O `PatrolAgent` é o leiloeiro da sua
própria disponibilidade. Implementado em
[`patrol.py`](sentinel_mas/agents/patrol.py) (leiloeiro) e
[`zone_coordinator.py`](sentinel_mas/agents/zone_coordinator.py) (licitadores).

```
ZC (ameaça ≥ HIGH) ──REQUEST patrol_wanted──▶ Patrol       (anuncia interesse)
Patrol (livre, há procura) ──CFP──▶ todos os ZCs           (call-for-proposals)
ZC_datacenter  ──PROPOSE bid=3──▶ Patrol                   (licita = nível de ameaça)
ZC_work_room_1 ──PROPOSE bid=2──▶ Patrol
Patrol ──ACCEPT-PROPOSAL──▶ ZC_datacenter                  (maior bid ganha)
Patrol ──REJECT-PROPOSAL──▶ ZC_work_room_1                 (rejeita os restantes)
Patrol ──(executa missão na zona vencedora)──▶ patrol_report
```

**Regras:**
- O **bid** de cada zona = o seu nível de ameaça (desempate por `anomaly_score`).
- O vencedor marca `patrol_status = en_route` e deixa de licitar até a missão acabar.
- Os perdedores continuam a licitar nos leilões seguintes — quando o robô fica
  livre, é a vez do próximo mais urgente.
- Se a navegação falhar, a zona volta a poder licitar (não fica presa).

**Para veres:** dispara duas zonas em alta ao mesmo tempo, ex.: combo `b` no
`datacenter` (CRITICAL) e evento `4` no `work_room_1` (HIGH). No terminal vês o
`CFP → PROPOSE → winner` e o robô a ir primeiro ao datacenter; o work_room_1 espera e é
servido a seguir.

---

## Casos de uso para experimentar (modo `--interactive`)

O menu tem **eventos individuais** (1-6) e **cenários/combos** (a-e). Um combo
dispara vários eventos em rajada para a mesma zona, para testares as correlações
multi-modalidade da tabela. Em cada um, escreves a escolha e depois a zona.

**Eventos individuais:**

| # | Evento | Crença que define |
|---|--------|-------------------|
| 1 | `motion_detected` | `physical_presence`, incrementa `motion_count` |
| 2 | `face_detected` desconhecido | `unknown_face` (mismatch) |
| 3 | `face_detected` alice | `last_identity` (autorizado), retira `unknown_face` |
| 4 | `cyber_anomaly` HIGH (0.92) | `cyber_anomaly` |
| 5 | `cyber_anomaly` CRITICAL (0.98) | `cyber_anomaly` |
| 6 | `patrol_report` clear | reset da zona (de-escala) |

**Cenários (rajada correlacionada):**

| Combo | Eventos | Resultado típico |
|-------|---------|------------------|
| `a` | motion + face mismatch | intruder → `HIGH` (lobby/break_room: visual intruder) |
| `b` | cyber + motion (sem face) | `CRITICAL` no datacenter (presença durante anomalia) |
| `c` | cyber + motion + face mismatch | `CRITICAL` correlated incident |
| `d` | cyber + face autorizada | `LOW` benign admin (sem escalada) |
| `e` | cyber só | `HIGH` remote attack / compromised workstation |

> A severidade depende da zona — ex.: o combo `b` é CRÍTICO no `datacenter`,
> mas numa work_room (sem camera) só consegues motion+cyber via eventos 1+4. Vê a
> tabela de fusão por zona acima.

### Exemplos rápidos
- **Incidente crítico correlacionado:** combo `c` no `datacenter` → `*** ALERT *** threat=3`.
- **Admin benigno:** combo `d` no `datacenter` → fica `LOW`, sem patrulha nem alerta.
- **Loitering:** evento `1` três vezes no `corridor` → `suspicious loitering` (MEDIUM).
- **Workstation comprometida:** evento `4` numa `work_room` → `compromised workstation` (HIGH) → patrulha.
- **De-escalar:** evento `6` na zona → volta a `LOW` e limpa as crenças.

---

## Ficheiros

| Ficheiro | Papel |
|----------|-------|
| [`main.py`](sentinel_mas/main.py) | Launcher: XMPP embutido + agentes (`--web` dashboard, `--interactive` injetor terminal) |
| [`dashboard.py`](sentinel_mas/dashboard.py) | Dashboard web (aiohttp) + injetor acionado pelo browser |
| [`dashboard_log.py`](sentinel_mas/dashboard_log.py) | Buffer de timeline partilhado que alimenta o dashboard |
| [`run_color.py`](sentinel_mas/run_color.py) | Wrapper de visualização com cores por agente |
| [`kill.ps1`](sentinel_mas/kill.ps1) | Mata processos do MAS pendurados e liberta as portas |
| [`config/settings.py`](sentinel_mas/config/settings.py) | Zonas, JIDs, portas, sensores, limiares de ameaça |
| [`agents/zone_coordinator.py`](sentinel_mas/agents/zone_coordinator.py) | Agente BDI deliberativo + licitador Contract Net |
| [`agents/threat_fusion.py`](sentinel_mas/agents/threat_fusion.py) | Regras de fusão de ameaça por zona |
| [`agents/patrol.py`](sentinel_mas/agents/patrol.py) | Agente híbrido: leiloeiro Contract Net + missão + stub de navegação |
| [`agents/reactive_agents.py`](sentinel_mas/agents/reactive_agents.py) | Sensores reativos + sink de alertas |
| [`agents/console_injector.py`](sentinel_mas/agents/console_injector.py) | Injetor manual de eventos em-processo (`--interactive`) |
| [`utils/bdi.py`](sentinel_mas/utils/bdi.py) | Motor BDI (crenças, planos, desejos) |
| [`utils/messaging.py`](sentinel_mas/utils/messaging.py) | Construção de mensagens FIPA-ACL |

---

## Resolução de problemas

**`main.py` mostra "could not start the XMPP server"**
Outra instância já tem a porta 5322 (tipicamente um MAS de uma execução anterior
que ficou pendurado, ou um lançado com o Python errado). Limpa tudo com:

```powershell
.\kill.ps1
```

Depois arranca de novo. O `kill.ps1` mata por porta e por linha de comando, e
confirma que as portas ficaram livres.

**Lancei pelo botão ▶ do VS Code e dá conflito / erros de import**
O botão ▶ usa o interpreter que o VS Code tem selecionado, que pode ser o Python
do sistema em vez do `.venv` — isso lança um MAS com bibliotecas diferentes e
gera conflitos de porta. **Arranca sempre pelo terminal com `(.venv)` no prompt**,
ou corrige o interpreter: `Ctrl+Shift+P` → "Python: Select Interpreter" →
escolhe `.venv\Scripts\python.exe`.

**Fechar o MAS de forma limpa**
Usa `Ctrl+C` no terminal (não feches a janela à força), para libertar a porta.

**ROS2 / robô real**
O `PatrolAgent` usa um *stub* de navegação. A integração real (PPO via
stable-baselines3 + tópicos ROS2 `/cmd_vel`, `/odom`, `/scan`) liga-se quando
`ROS2_ENABLED = True` em [`config/settings.py`](sentinel_mas/config/settings.py).
