# SentinelMAS — Ambiente Webots da Empresa (Challenge 4)

Ambiente de simulação Webots que suporta o artigo *"SentinelMAS"* (Challenge 4):
um robô de vigilância ciber-físico autónomo que funde telemetria digital e
controlo de acesso físico numa única camada de raciocínio multi-agente.

## O ambiente

Planta de uma empresa (20 m × 12 m) com as seguintes zonas, todas ligadas por
um corredor central:

```
+--------+--------+--------+--------+------------+
| Sala   | Sala   | Sala   | Sala   | Datacenter |
| Trab. 1| Trab. 2| Trab. 3| Trab. 4| [cam+PIR]  |
+--p-----+--p-----+--p-----+--p-----+----p-------+
|              C O R R E D O R   [PIR]   (doca)  |
+------p--------------------+------p-------------+
|  LOBBY (entrada)  [PIR]   |  Sala de convívio  |
|  [câmara checkpoint]      |  [PIR]             |
+-------==------------------+--------------------+
        entrada
```

- **Lobby (entrada)** — receção, sofá de espera; os funcionários entram aqui.
- **Checkpoint facial** — porta lobby→corredor controlada por uma câmara de
  reconhecimento facial (`FACECAM_CHECKPOINT`).
- **4 salas de trabalho** — cada uma com 2 secretárias, monitores, teclados e
  cadeiras de escritório.
- **Datacenter** — 4 racks de servidores, consola; o acesso é controlado por
  uma segunda câmara de reconhecimento facial (`FACECAM_DATACENTER`) e apenas
  pessoal autorizado (Bruno) pode entrar.
- **Sala de convívio** — mesa, cadeiras, sofá.
- **Sensores de movimento (PIR)** em todas as zonas (8 sensores), tal como no
  artigo, aproximados por `DistanceSensor`s do Webots.
- **Robô de patrulha** com farol, câmara de reconhecimento e doca no corredor.

## Mapeamento artigo ↔ simulação

| Agente no artigo            | Controlador Webots                      |
|-----------------------------|-----------------------------------------|
| MotionAgent (PIR)           | `controllers/motion_agent`             |
| FaceIDAgent (ArcFace)       | `controllers/face_id_agent`            |
| CyberSentinelAgent          | `controllers/cyber_sentinel_agent`     |
| PatrolAgent (Nav2 + PPO)    | `controllers/patrol_agent`             |
| ZoneCoordinator + AlertAgent| `controllers/security_supervisor`      |
| StaffRequestAgent           | ação `staff_request` em `person`       |

Notas de fidelidade:

- O **reconhecimento facial** usa o nó `Recognition` da câmara do Webots como
  proxy do pipeline ArcFace/InsightFace: o campo `model` de cada pessoa faz o
  papel do embedding e a galeria de funcionários enrolados está em
  `face_id_agent.py`. Caras fora da galeria são rejeitadas como `UNKNOWN`
  (open-set), exatamente como descrito no artigo.
- Os **PIR** são `DistanceSensor`s em leque com calibração de linha de base —
  a mesma aproximação referida na secção de seleção do simulador do artigo.
- O **CyberSentinelAgent** corre em cada rack e avalia o fluxo de comandos do
  servidor contra regras mapeadas em técnicas **MITRE ATT&CK** (T1485, T1490,
  T1059.x, T1003.x). Ao detetar um comando malicioso lança um `CYBER_ALERT` e
  o supervisor **tranca todas as portas** (`canBeOpen = FALSE`) — lockdown.
- A **navegação** do robô e o movimento das pessoas são cinemáticos
  (waypoints pelo corredor), um proxy simples da pilha ROS 2 / Nav2 + política
  PPO do artigo. No sistema real, o raciocínio do `security_supervisor` corre
  descentralizado em SPADE sobre FIPA-ACL; aqui está centralizado num único
  supervisor por simplicidade de simulação.
- As mensagens entre agentes (JSON sobre `Emitter`/`Receiver`, canal 1) fazem
  o papel das *beliefs* tipadas FIPA-ACL.

## Como executar

1. Instalar o [Webots R2023b](https://cyberbotics.com) (ou mais recente).
2. Abrir `worlds/sentinelmas_office.wbt`.
3. Premir play. O guião corre sozinho (~4 min); o estado do sistema e o
   registo de eventos aparecem como overlay na janela 3D e nas consolas.

> Os PROTOs standard (paredes, portas, mobiliário) são descarregados
> automaticamente via `EXTERNPROTO`, pelo que é necessária ligação à internet
> na primeira execução.

## Guião da demonstração

| t (s) | Evento |
|-------|--------|
| 2–35  | Alice, Bruno e Carla entram no lobby; o checkpoint facial valida cada um e abre a porta. Alice vai para a sala de trabalho 2, Carla para a sala de convívio. |
| ~25   | Bruno é validado também na câmara do datacenter (único autorizado) e entra. |
| 45    | Um **intruso** entra no lobby. A câmara do checkpoint não o encontra na galeria → acesso **negado** + alerta de intrusão. |
| ~55   | O supervisor **despacha o robô de patrulha**; o intruso força a porta e dirige-se ao datacenter pelo corredor. |
| ~75   | O robô interceta o intruso no corredor, **detém-no** (a pessoa fica imobilizada), verifica a identidade no local com a própria câmara e guarda-o. |
| 110   | O agente do **rack_2** deteta um comando malicioso (`powershell -enc …` → T1059.001): LED do rack fica vermelho, `CYBER_ALERT` é emitido. |
| ~112  | **LOCKDOWN**: todas as portas são trancadas, funcionários abrigam-se no lugar, o robô é enviado a investigar o datacenter. |
| ~125  | O robô reporta quem está presente no datacenter → escalação para o operador; o lockdown é levantado pouco depois. |
| ~250  | Carla faz um **pedido de assistência** (StaffRequestAgent) — arbitrado pela mesma via dos alertas autónomos; o robô responde e regressa à doca. |

## Estrutura do repositório

```
worlds/
  sentinelmas_office.wbt        # planta da empresa, sensores, robôs, pessoas
controllers/
  common/zones.py               # zonas, portas e rotas pelo corredor
  person/                       # funcionários e intruso (guiões de movimento)
  face_id_agent/                # câmaras de reconhecimento facial (2 gates)
  motion_agent/                 # sensores PIR (1 por zona)
  cyber_sentinel_agent/         # agente de telemetria de cada servidor
  patrol_agent/                 # robô de patrulha (deter / investigar / assistir)
  security_supervisor/          # coordenação, portas, lockdown, alertas, HUD
```

## Protocolo de mensagens (canal 1)

| Tipo            | Origem → Destino                | Conteúdo |
|-----------------|---------------------------------|----------|
| `FACE`          | face_id_agent → supervisor      | gate, identidade, modelo |
| `ACCESS_REQUEST`/`_GRANTED`/`_DENIED` | pessoa ↔ supervisor | nome, gate |
| `MOTION`        | motion_agent → supervisor       | zona |
| `CYBER_ALERT`   | cyber_sentinel → supervisor     | host, comando, técnica ATT&CK |
| `LOCKDOWN`/`LOCKDOWN_CLEAR` | supervisor → todos  | motivo |
| `DISPATCH`      | supervisor → patrol_agent       | tipo, alvo, posição, motivo |
| `TARGET_POS`    | supervisor → patrol_agent       | posição atual do alvo |
| `DETAIN`/`DETAINED` | patrol_agent → pessoa/supervisor | nome, verificação facial |
| `REPORT`/`ASSIST_DONE` | patrol_agent → supervisor | zona, presentes |
| `STAFF_REQUEST` | pessoa → supervisor             | nome, posição |
