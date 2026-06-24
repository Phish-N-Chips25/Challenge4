# Regras de Threat Scoring por Zona

> Documento atualizado ao longo da sessão de design.

---

## LOBBY
**Sensores:** Câmara facial + PIR (movimento)**  
**Papel:** Zona pública de entrada — registo de quem entra, não zona de alerta.

| Score | Condição |
|---|---|
| LOW | Sem atividade |
| MEDIUM | Movimento detetado / pessoa presente (autorizada ou não) |

> A câmara serve para registar a identidade e passá-la às zonas seguintes.
> Não faz sentido HIGH ou CRITICAL aqui — qualquer pessoa pode estar no lobby.

---

## EXTERIOR (Break Room)
**Sensores:** Câmara facial + PIR  
**Papel:** Zona pública exterior antes do lobby — mesmo critério que o lobby.

| Score | Condição |
|---|---|
| LOW | Sem atividade |
| MEDIUM | Movimento detetado / pessoa presente (autorizada ou não) |

---

## WORK ROOMS (1–4)
**Sensores:** Câmara facial + PIR + sensor cyber  
**Papel:** Zona semi-restrita — só funcionários autorizados devem estar presentes.

| Score | Condição |
|---|---|
| LOW | Sem atividade — ou — funcionário autorizado presente |
| MEDIUM | Movimento detetado sem identificação facial |
| HIGH | Pessoa não autorizada + movimento — ou — anomalia cyber sem presença física — ou — presença não identificada durante anomalia cyber |
| CRITICAL | Pessoa não autorizada + movimento + anomalia cyber ativa |

---

## SERVER ROOM / DATACENTER
**Sensores:** Câmara facial + PIR + sensor cyber  
**Papel:** Zona mais crítica — qualquer intruso físico confirmado é CRITICAL.

| Score | Condição |
|---|---|
| LOW | Sem atividade |
| MEDIUM | Funcionário autorizado presente — ou — funcionário autorizado durante anomalia cyber (possível insider threat) |
| HIGH | Anomalia cyber sem presença física — ou — presença não identificada sem confirmação câmara |
| CRITICAL | Pessoa não autorizada + movimento — ou — pessoa não autorizada + anomalia cyber — ou — presença não identificada + anomalia cyber |
