import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import bcrypt
import servidor
from rede import read_json, atomic_json


class ServerTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Caminhos de instalação Windows')
    def test_finds_per_user_installation_without_docker_on_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / 'AppData/Local'
            binary = local / 'Programs/DockerDesktop/resources/bin/docker.exe'
            binary.parent.mkdir(parents=True)
            binary.touch()
            with patch.dict(os.environ, {'LOCALAPPDATA': str(local), 'ProgramFiles': str(Path(tmp) / 'Programs')}, clear=True), \
                 patch('servidor.shutil.which', return_value=None):
                controller = servidor.LabController(tmp)
                controller.find_docker()
            self.assertEqual(controller.docker, str(binary.resolve()))

    def test_cli_environment_finds_credential_helper_without_changing_system_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / 'Docker/resources/bin/docker.exe'
            controller = servidor.LabController(tmp)
            controller.docker = str(binary)
            with patch.dict(os.environ, {'PATH': 'PATH_ANTES_DA_INSTALACAO'}), \
                 patch('servidor.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'linux', '')) as run:
                controller.run([str(binary), 'info'])
                env = run.call_args.kwargs['env']
                self.assertEqual(env['PATH'].split(os.pathsep)[0], str(binary.parent.resolve()))
                self.assertEqual(os.environ['PATH'], 'PATH_ANTES_DA_INSTALACAO')

    @unittest.skipUnless(os.name == 'nt', 'Inicialização do Docker Desktop no Windows')
    def test_fallback_launches_desktop_from_per_user_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp) / 'Programs/DockerDesktop'
            install.mkdir(parents=True)
            desktop = install / 'Docker Desktop.exe'
            desktop.touch()
            controller = servidor.LabController(tmp)
            controller.docker = str(install / 'resources/bin/docker.exe')
            with patch('servidor.subprocess.Popen') as launch:
                controller.launch_desktop()
            self.assertEqual(launch.call_args.args[0], [str(desktop)])
            self.assertEqual(launch.call_args.kwargs['startupinfo'].wShowWindow, 0)

    @unittest.skipUnless(os.name == 'nt', 'Inicialização do Docker Desktop no Windows')
    def test_desktop_cli_timeout_uses_fallback_and_does_not_change_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = servidor.LabController(tmp)
            controller.docker = 'docker.exe'
            with patch.object(controller, 'find_docker'), \
                 patch.object(controller, 'engine_ready', side_effect=[False, True]), \
                 patch.object(controller, 'run', side_effect=servidor.LabError('timeout')), \
                 patch.object(controller, 'launch_desktop') as launch:
                self.assertTrue(controller.ensure_engine(start=True))
            launch.assert_called_once()
            self.assertEqual(controller.context, ['--context', 'desktop-linux'])

    @unittest.skipUnless(os.name == 'nt', 'Inicialização do Docker Desktop no Windows')
    def test_engine_failure_records_original_docker_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = servidor.LabController(tmp)
            controller.docker = 'docker.exe'
            def not_ready():
                controller.last_engine_detail = 'context desktop-linux: context not found'
                return False
            with patch.object(controller, 'find_docker'), \
                 patch.object(controller, 'engine_ready', side_effect=not_ready), \
                 patch.object(controller, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')), \
                 patch('servidor.time.monotonic', side_effect=[0, 151]):
                with self.assertRaises(servidor.LabError) as error:
                    controller.ensure_engine(start=True)
            self.assertEqual(error.exception.kind, 'docker_not_ready')
            self.assertIn('context not found', (Path(tmp) / 'runtime/painel-acao.log').read_text(encoding='utf-8'))

    def test_unexpected_failure_records_trace_and_redacts_wifi_password(self):
        with tempfile.TemporaryDirectory() as tmp:
            atomic_json(Path(tmp) / 'config.local.json', {'wifi_password': 'SENHA_WIFI_APENAS_TESTE'})
            controller = servidor.LabController(tmp)
            try:
                raise FileNotFoundError('arquivo ausente: SENHA_WIFI_APENAS_TESTE')
            except FileNotFoundError as error:
                self.assertTrue(controller.record_error(error, 'Teste de início'))
            log = (Path(tmp) / 'runtime/painel-acao.log').read_text(encoding='utf-8')
            self.assertIn('FileNotFoundError', log)
            self.assertIn('Traceback', log)
            self.assertNotIn('SENHA_WIFI_APENAS_TESTE', log)
            self.assertIn('[oculto]', log)

    def test_log_permission_failure_does_not_hide_original_error(self):
        controller = servidor.LabController('.')
        with patch.object(controller, 'log', side_effect=PermissionError('sem acesso')):
            self.assertFalse(controller.record_error(FileNotFoundError('original'), 'iniciar'))

    def test_download_network_failure_has_actionable_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = servidor.LabController(tmp)
            result = subprocess.CompletedProcess([], 1, '', 'lookup registry-1.docker.io: no such host')
            with patch('servidor.subprocess.run', return_value=result):
                with self.assertRaises(servidor.LabError) as error:
                    controller.run(['docker', 'compose', 'up'])
            self.assertEqual(error.exception.kind, 'docker_network')
            self.assertIn('no such host', (Path(tmp) / 'runtime/painel-acao.log').read_text(encoding='utf-8'))

    def test_first_preparation_and_network_toggle_preserve_credentials_and_ports(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            settings = servidor.prepare_files(folder, False)
            self.assertEqual(settings['mqtt_port'], 18830)
            self.assertTrue(servidor.initialized(folder))
            secrets = read_json(folder / 'runtime/secrets.json')
            self.assertEqual(len(secrets), 8)
            self.assertTrue(all(len(value) >= 20 for value in secrets.values()))
            sql_hash = hashlib.sha256((folder / 'runtime/01-init.sql').read_bytes()).hexdigest()
            config = read_json(folder / 'runtime/base.hocon')
            self.assertEqual(config['authentication'][0]['password_hash_algorithm']['name'], 'bcrypt')
            self.assertEqual(config['authorization']['no_match'], 'deny')
            settings = servidor.prepare_files(folder, True)
            self.assertEqual(settings['bind'], '0.0.0.0')
            self.assertEqual(settings['profile'], 'server')
            self.assertEqual(settings['mqtt_port'], 18830)
            self.assertEqual(read_json(folder / 'runtime/secrets.json'), secrets)
            self.assertEqual(hashlib.sha256((folder / 'runtime/01-init.sql').read_bytes()).hexdigest(), sql_hash)
            self.assertIn('BIND_ADDRESS=0.0.0.0', (folder / 'runtime/compose.env').read_text())

    def test_partial_preparation_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'runtime/secrets.json'
            atomic_json(path, {'dashboard': 'senha-existente-nao-substituir'})
            original = path.read_bytes()
            with self.assertRaises(servidor.LabError):
                servidor.prepare_files(tmp, True)
            self.assertEqual(path.read_bytes(), original)

    def test_cli_reinitialization_keeps_ports_chosen_by_panel(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            servidor.prepare_files(folder, False)
            servidor.prepare_files(folder, True)
            import lab
            from contextlib import redirect_stdout
            import io
            old_root, old_runtime = lab.ROOT, lab.RUNTIME
            try:
                lab.ROOT, lab.RUNTIME = folder, folder / 'runtime'
                with redirect_stdout(io.StringIO()):
                    lab.init('server')
                self.assertEqual(read_json(folder / 'runtime/settings.json')['mqtt_port'], 18830)
            finally:
                lab.ROOT, lab.RUNTIME = old_root, old_runtime

    def test_stop_targets_only_dedicated_services_without_removing_volumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = servidor.LabController(tmp)
            controller.docker = 'docker.exe'
            controller.context = ['--context', 'desktop-linux']
            with patch.object(servidor, 'initialized', return_value=True), \
                 patch.object(controller, 'ensure_engine', return_value=True) as engine, \
                 patch.object(controller, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
                self.assertTrue(controller.stop()['stopped'])
            engine.assert_called_once_with(start=False)
            command = run.call_args_list[0].args[0]
            self.assertIn('desktop-linux', command)
            self.assertEqual(command[command.index('--project-name') + 1], 'atleta-lab')
            self.assertEqual(command[-5:], ['stop', '--timeout', '30', 'emqx', 'mysql'])
            self.assertFalse({'down', 'rm', '--volumes', '-v'} & set(command))

    def test_stop_does_not_start_docker_when_engine_is_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = servidor.LabController(tmp)
            with patch.object(servidor, 'initialized', return_value=True), \
                 patch.object(controller, 'ensure_engine', return_value=False), patch.object(controller, 'run') as run:
                self.assertTrue(controller.stop()['engine_offline'])
                run.assert_not_called()

    def test_new_folder_cannot_replace_credentials_for_existing_volumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = servidor.LabController(tmp)
            controller.docker = 'docker.exe'
            with patch.object(controller, 'run', return_value=subprocess.CompletedProcess([], 0, 'atleta-lab_mysql_data', '')):
                with self.assertRaises(servidor.LabError):
                    controller.check_existing_project()
            self.assertFalse((Path(tmp) / 'runtime/secrets.json').exists())

    def test_existing_engine_is_used_without_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = servidor.LabController(tmp)
            with patch.object(controller, 'find_docker'), patch.object(controller, 'engine_ready', return_value=True), \
                 patch.object(controller, 'run') as run:
                self.assertTrue(controller.ensure_engine(start=True))
                run.assert_not_called()

    def test_start_checks_health_before_reporting_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = servidor.LabController(tmp)
            controller.docker = 'docker.exe'
            with patch.object(controller, 'ensure_engine'), patch.object(controller, 'check_existing_project'), \
                 patch.object(servidor, 'prepare_files', return_value={'mqtt_port': 1883, 'dashboard_port': 18083}), \
                 patch.object(controller, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')), \
                 patch.object(servidor, 'inspect_pair', return_value={'mqtt_online': True, 'dashboard_online': False}):
                with self.assertRaises(servidor.LabError):
                    controller.start(True)

    def test_log_masks_generated_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            atomic_json(Path(tmp) / 'runtime/secrets.json', {'dashboard': 'SEGREDO_PRIVADO_DE_TESTE'})
            controller = servidor.LabController(tmp)
            controller.log('Falha: SEGREDO_PRIVADO_DE_TESTE')
            content = (Path(tmp) / 'runtime/painel-acao.log').read_text()
            self.assertNotIn('SEGREDO_PRIVADO_DE_TESTE', content)
            self.assertIn('[oculto]', content)


if __name__ == '__main__':
    unittest.main(verbosity=2)
