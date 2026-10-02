"""Controle da stack dedicada atleta-lab, com preparação e Docker Desktop locais."""
from __future__ import annotations

from contextlib import contextmanager, redirect_stdout
from datetime import datetime
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback

from rede import atomic_json, read_json, inspect_pair, port

PROJECT = 'atleta-lab'
TEMPLATES = ('compose.yaml', 'config.example.json', 'sql/01-schema.sql',
             'emqx/rule.sql', 'emqx/insert.sql', 'emqx/authentication.sql', 'emqx/authorization.sql')
PRIVATE_FILES = ('secrets.json', 'settings.json', 'compose.env', '01-init.sql', 'base.hocon')
DOCKER_DOWNLOAD = 'https://docs.docker.com/desktop/setup/install/windows-install/'


def desktop_locations():
    """Instalações oficiais para todos os usuários e apenas para o usuário atual."""
    locations = []
    local = os.environ.get('LOCALAPPDATA')
    if local:
        locations += [Path(local) / 'Programs/DockerDesktop', Path(local) / 'Docker']
    locations.append(Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Docker/Docker')
    return locations


class LabError(Exception):
    def __init__(self, message, kind='operation'):
        super().__init__(message)
        self.kind = kind


def kit_source():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'kit'
    return Path(__file__).resolve().parents[1]


def initialized(folder):
    return all((Path(folder) / 'runtime' / name).is_file() for name in PRIVATE_FILES)


def network_enabled(folder):
    try:
        settings = read_json(Path(folder) / 'runtime/settings.json')
        return settings.get('bind', '0.0.0.0') != '127.0.0.1'
    except (OSError, ValueError):
        return (Path(folder) / 'migracao/manifest.json').is_file()


@contextmanager
def operation_lock(folder):
    runtime = Path(folder) / 'runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / 'painel.lock').open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise LabError('Outra janela já está preparando este laboratório. Aguarde a conclusão.') from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def prepare_files(folder, allow_network, source=None):
    folder, source = Path(folder), Path(source or kit_source())
    folder.mkdir(parents=True, exist_ok=True)
    runtime = folder / 'runtime'
    existing_private = [name for name in PRIVATE_FILES if (runtime / name).exists()]
    if existing_private and not initialized(folder):
        raise LabError('A preparação existente está incompleta. Preserve a pasta runtime e consulte o registro de detalhes.')
    for name in TEMPLATES:
        target = folder / name
        if not target.exists():
            origin = source / name
            if not origin.is_file():
                raise LabError('Os arquivos do laboratório estão incompletos. Use o executável atualizado ou o pacote completo.')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(origin, target)
    if not initialized(folder):
        # Reutiliza exatamente o gerador SQL/EMQX já validado neste projeto.
        # O módulo é incluído no EXE; não executa outro interpretador Python.
        if not getattr(sys, 'frozen', False):
            tools_path = str(Path(__file__).resolve().parents[1] / 'tools')
            if tools_path not in sys.path:
                sys.path.insert(0, tools_path)
        import lab
        old_root, old_runtime = lab.ROOT, lab.RUNTIME
        try:
            lab.ROOT, lab.RUNTIME = folder, runtime
            with redirect_stdout(io.StringIO()):
                lab.init('server' if allow_network else 'local')
        finally:
            lab.ROOT, lab.RUNTIME = old_root, old_runtime
    settings = read_json(runtime / 'settings.json')
    for key in ('mqtt_port', 'dashboard_port', 'mysql_port'):
        if port(settings.get(key), None) is None:
            raise LabError('As portas na configuração do laboratório são inválidas.')
    bind = '0.0.0.0' if allow_network else '127.0.0.1'
    env_path = runtime / 'compose.env'
    env = env_path.read_text(encoding='utf-8-sig')
    if len(re.findall(r'^BIND_ADDRESS=', env, re.M)) != 1:
        raise LabError('O arquivo compose.env precisa conter um único BIND_ADDRESS.')
    env = re.sub(r'^BIND_ADDRESS=.*$', f'BIND_ADDRESS={bind}', env, flags=re.M)
    settings.update(bind=bind, profile='server' if allow_network else 'local')
    # Somente bind/perfil mudam; portas, credenciais e volumes permanecem.
    temp = runtime / 'compose.env.tmp'
    temp.write_text(env, encoding='utf-8')
    os.replace(temp, env_path)
    atomic_json(runtime / 'settings.json', settings)
    return settings


class LabController:
    def __init__(self, folder, progress=None):
        self.folder = Path(folder).resolve()
        self.progress = progress or (lambda text: None)
        self.docker = None
        self.context = ['--context', 'desktop-linux'] if os.name == 'nt' else []
        self.last_engine_detail = ''

    def log(self, text):
        path = self.folder / 'runtime/painel-acao.log'
        path.parent.mkdir(parents=True, exist_ok=True)
        values = []
        for source in (path.parent / 'secrets.json', self.folder / 'config.local.json',
                       path.parent / 'device-config.json'):
            try:
                data = read_json(source)
                values.extend(value for key, value in data.items()
                              if source.name == 'secrets.json' or any(
                                  part in key.lower() for part in ('password', 'senha', 'secret', 'token')))
            except (OSError, ValueError, AttributeError):
                pass
        for value in sorted((v for v in values if isinstance(v, str) and v), key=len, reverse=True):
            text = text.replace(value, '[oculto]')
        with path.open('a', encoding='utf-8') as file:
            file.write(f'[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}\n')

    def record_error(self, error, operation):
        try:
            detail = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
            self.log(f'Falha em {operation}:\n{detail}')
            return True
        except OSError:
            # A mensagem de permissão na interface continua disponível mesmo sem log.
            return False

    def docker_environment(self):
        env = dict(os.environ)
        if self.docker:
            # Um EXE já aberto pode ter herdado o PATH anterior à instalação do Docker.
            # O cliente também precisa localizar docker-credential-desktop nesse diretório.
            binary_dir = str(Path(self.docker).resolve().parent)
            env['PATH'] = binary_dir + os.pathsep + env.get('PATH', '')
        return env

    def run(self, args, timeout=30, check=True):
        kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        command = subprocess.list2cmdline([str(arg) for arg in args])
        try:
            result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                    timeout=timeout, cwd=self.folder, env=self.docker_environment(), **kwargs)
        except subprocess.TimeoutExpired as exc:
            output = '\n'.join(value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value
                               for value in (exc.stdout, exc.stderr) if value)
            self.log(f'Tempo excedido ({timeout}s): {command}\n{output}')
            raise LabError('A operação demorou além do esperado. Consulte os detalhes e tente novamente.') from exc
        if check and result.returncode:
            self.log(f'Comando falhou: {command}\n' + result.stdout + '\n' + result.stderr)
            body = (result.stdout + result.stderr).lower()
            if any(text in body for text in ('port is already allocated', 'address already in use', 'ports are not available')):
                raise LabError('Uma porta do laboratório já está ocupada por outro programa. Consulte os detalhes.', 'port_busy')
            if any(text in body for text in ('no such host', 'i/o timeout', 'tls handshake timeout', 'proxyconnect', 'network is unreachable')):
                raise LabError('Falha de rede no Docker. Confira a Internet ou o proxy desse PC e veja o erro em Ver detalhes.', 'docker_network')
            raise LabError('O Docker não concluiu a operação. O registro de detalhes mostra o motivo.')
        return result

    def find_docker(self):
        paths = [shutil.which('docker')]
        if os.name == 'nt':
            paths += [str(root / 'resources/bin/docker.exe') for root in desktop_locations()]
        self.docker = next((str(Path(path).resolve()) for path in paths if path and Path(path).is_file()), None)
        if not self.docker:
            raise LabError('Instale o Docker Desktop uma vez. Depois, este botão iniciará o laboratório automaticamente.', 'docker_missing')
        self.log(f'Cliente Docker localizado: {self.docker}')

    def launch_desktop(self):
        candidates = []
        if self.docker and len(Path(self.docker).parents) >= 3:
            candidates.append(Path(self.docker).parents[2] / 'Docker Desktop.exe')
        candidates += [root / 'Docker Desktop.exe' for root in desktop_locations()]
        desktop = next((path for path in candidates if path.is_file()), None)
        if desktop is None:
            raise LabError('Não foi possível localizar o Docker Desktop. Confira a instalação.', 'docker_missing')
        self.log(f'Iniciando Docker Desktop: {desktop}')
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        subprocess.Popen([str(desktop)], startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW,
                         env=self.docker_environment(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def engine_ready(self):
        try:
            result = self.run([self.docker, *self.context, 'info', '--format', '{{.OSType}}'], timeout=8, check=False)
        except LabError as exc:
            self.last_engine_detail = str(exc)
            return False
        ready = result.returncode == 0 and result.stdout.strip() == 'linux'
        self.last_engine_detail = '' if ready else f'Código {result.returncode}:\n{result.stdout}\n{result.stderr}'
        return ready

    def ensure_engine(self, start):
        self.progress('1/4 • Verificando o Docker…')
        self.find_docker()
        if self.engine_ready():
            return True
        if not start:
            return False
        if os.name != 'nt':
            raise LabError('Inicie o serviço Docker deste computador e tente novamente.')
        self.progress('1/4 • Iniciando o Docker Desktop…')
        self.log('Docker Linux indisponível antes de iniciar:\n' + self.last_engine_detail)
        try:
            result = self.run([self.docker, 'desktop', 'start', '--detach'], timeout=30, check=False)
            launched = result.returncode == 0
            self.log('Resultado de docker desktop start:\n' + result.stdout + '\n' + result.stderr)
        except LabError:
            launched = False
        if not launched:
            self.launch_desktop()
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            if self.engine_ready():
                return True
            time.sleep(2)
        self.log('Docker Linux não ficou pronto:\n' + self.last_engine_detail)
        raise LabError('Abra o Docker Desktop, conclua a configuração inicial e confira se o mecanismo Linux está funcionando. Depois tente novamente.', 'docker_not_ready')

    def compose_args(self, *args):
        return [self.docker, *self.context, 'compose', '--project-name', PROJECT,
                '--env-file', str(self.folder / 'runtime/compose.env'), '-f', str(self.folder / 'compose.yaml'), *args]

    def check_existing_project(self):
        if initialized(self.folder):
            return
        result = self.run([self.docker, *self.context, 'volume', 'ls', '--filter',
                           f'label=com.docker.compose.project={PROJECT}', '--format', '{{.Name}}'])
        if result.stdout.strip():
            raise LabError('Já existem dados de atleta-lab neste Docker. Abra o painel na pasta original do laboratório para usar suas credenciais.')

    def start(self, allow_network):
        with operation_lock(self.folder):
            self.log('Início solicitado pelo painel.')
            from migracao import load_history, restore_history, MigrationError
            try:
                snapshot = load_history(self.folder)
            except MigrationError as error:
                raise LabError(str(error)) from None
            self.ensure_engine(start=True)
            self.check_existing_project()
            self.progress('2/4 • Preparando o banco e as configurações…')
            settings = prepare_files(self.folder, allow_network)
            self.run([self.docker, *self.context, 'compose', 'version'])
            if snapshot is not None:
                self.progress('3/4 • Preparando MySQL e restaurando o histórico…')
                self.run(self.compose_args('up', '-d', '--wait', '--wait-timeout', '180', 'mysql'), timeout=900)
                try:
                    restored = restore_history(self.folder, snapshot)
                except MigrationError as error:
                    raise LabError(str(error)) from None
                self.log(f"Histórico conferido: {restored['rows_verified']} registros; {restored['rows_inserted']} restaurados nesta operação.")
            self.progress('3/4 • Iniciando EMQX e MySQL. O primeiro download pode demorar…')
            result = self.run(self.compose_args('up', '-d', '--wait', '--wait-timeout', '180', 'mysql', 'emqx'), timeout=900)
            self.log(result.stdout + '\n' + result.stderr)
            self.progress('4/4 • Conferindo o servidor e o Dashboard…')
            pair = settings['mqtt_port'], settings['dashboard_port']
            status = inspect_pair('127.0.0.1', pair)
            if not status['mqtt_online'] or not status['dashboard_online']:
                raise LabError('Os containers iniciaram, mas MQTT e Dashboard ainda não responderam. Clique em Atualizar IP para verificar novamente.')
            self.log('EMQX e MySQL saudáveis; MQTT e Dashboard responderam.')
            return {'started': True, 'settings': settings,
                    'dashboard_url': f"http://127.0.0.1:{settings['dashboard_port']}/"}

    def stop(self):
        with operation_lock(self.folder):
            if not initialized(self.folder):
                raise LabError('Este laboratório ainda não foi preparado pelo painel.')
            if not self.ensure_engine(start=False):
                return {'stopped': True, 'engine_offline': True}
            self.progress('Parando EMQX e MySQL; os dados serão preservados…')
            result = self.run(self.compose_args('stop', '--timeout', '30', 'emqx', 'mysql'), timeout=90)
            self.log(result.stdout + '\n' + result.stderr)
            result = self.run(self.compose_args('ps', '--status', 'running', '--services'))
            if {'mysql', 'emqx'} & set(result.stdout.split()):
                raise LabError('Um serviço ainda está em execução. Consulte os detalhes.')
            self.log('Laboratório parado; containers e volumes preservados.')
            return {'stopped': True, 'engine_offline': False}
