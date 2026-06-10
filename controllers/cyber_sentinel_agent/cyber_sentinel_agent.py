"""CyberSentinelAgent — agente de telemetria instalado em cada servidor.

Simula o pipeline Dual Sentinel do artigo: cada rack "executa" um fluxo de
comandos (telemetria de endpoint) e o agente avalia cada comando contra um
conjunto de regras mapeadas em tecnicas MITRE ATT&CK. Ao detetar um comando
malicioso, o agente:
  1. passa o LED de estado do rack para vermelho,
  2. publica um CYBER_ALERT no canal partilhado — o supervisor de seguranca
     responde trancando todas as portas (lockdown) e despachando o robo de
     patrulha para o datacenter.

O ataque e guiado: apenas o rack_2 injeta uma sequencia maliciosa, ao
instante ATTACK_TIME, para tornar o cenario do artigo reproduzivel.
"""

import json
import re

from controller import Robot

BENIGN_COMMANDS = [
    "systemctl status nginx",
    "df -h /var",
    "uptime",
    "tail -n 50 /var/log/auth.log",
    "ps aux --sort=-%cpu | head",
    "sha256sum /opt/app/release.tar.gz",
    "rsync -a /srv/data /backup/data",
    "journalctl -u postgres --since '5 min ago'",
]

# (padrao, tecnica MITRE ATT&CK, descricao)
MALICIOUS_RULES = [
    (r"rm\s+-rf\s+/", "T1485", "Destruicao de dados (rm -rf /)"),
    (r"vssadmin\s+delete\s+shadows", "T1490", "Inibir recuperacao do sistema"),
    (r"-enc\s+[A-Za-z0-9+/=]{16,}", "T1059.001", "PowerShell ofuscado em base64"),
    (r"nc\s+(-e|--exec)", "T1059", "Reverse shell via netcat"),
    (r"/etc/shadow", "T1003.008", "Dump de credenciais (/etc/shadow)"),
    (r"curl[^|]*\|\s*(sh|bash)", "T1059.004", "Download-and-execute via pipe"),
    (r"mimikatz", "T1003.001", "Ferramenta de dump de credenciais"),
]

# rack -> (instante do ataque, sequencia de comandos injetada)
SCRIPTED_ATTACKS = {
    "rack_2": (110.0, [
        "whoami /all",
        "powershell -nop -w hidden -enc SQBuAHYAbwBrAGUALQBXAGUAYgA=",
        "vssadmin delete shadows /all /quiet",
    ]),
}

COMMAND_PERIOD = 3.0      # s entre comandos do fluxo de telemetria
LED_BLINK_PERIOD = 1.0    # s do pisca verde em funcionamento normal


def check_command(command):
    """Devolve (tecnica, descricao) se o comando for malicioso, senao None."""
    for pattern, technique, description in MALICIOUS_RULES:
        if re.search(pattern, command, re.IGNORECASE):
            return technique, description
    return None


def main():
    robot = Robot()
    timestep = int(robot.getBasicTimeStep())
    host = robot.getName()

    led = robot.getDevice("status_led")
    emitter = robot.getDevice("emitter")

    attack_time, attack_commands = SCRIPTED_ATTACKS.get(host, (None, []))
    attack_queue = []
    attack_started = False

    next_command_at = 0.0
    benign_index = 0
    compromised = False

    print(f"[cyber] CyberSentinelAgent ativo em {host}"
          + (f" (ataque guiado em t={attack_time}s)" if attack_time else ""))

    while robot.step(timestep) != -1:
        now = robot.getTime()

        if not compromised:
            led.set(1 if int(now / LED_BLINK_PERIOD) % 2 == 0 else 0)
        else:
            led.set(2)  # vermelho fixo: host marcado como comprometido

        if attack_time is not None and now >= attack_time and not attack_started:
            attack_started = True
            attack_queue = list(attack_commands)

        if now < next_command_at:
            continue
        next_command_at = now + COMMAND_PERIOD

        if attack_queue:
            command = attack_queue.pop(0)
        else:
            command = BENIGN_COMMANDS[benign_index % len(BENIGN_COMMANDS)]
            benign_index += 1

        verdict = check_command(command)
        if verdict is None:
            continue

        technique, description = verdict
        print(f"[cyber] {host}: COMANDO MALICIOSO '{command}' "
              f"-> {technique} ({description})")
        if not compromised:
            compromised = True
            emitter.send(json.dumps({
                "type": "CYBER_ALERT",
                "host": host,
                "command": command,
                "technique": technique,
                "description": description,
            }).encode())


if __name__ == "__main__":
    main()
