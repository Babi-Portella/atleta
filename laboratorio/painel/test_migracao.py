import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import migracao
from rede import atomic_json, find_folder
from servidor import network_enabled


class MigrationTests(unittest.TestCase):
    def write_snapshot(self, folder, rows):
        directory = Path(folder) / 'migracao'
        directory.mkdir(exist_ok=True)
        raw = b''.join(migracao.encoded(row) for row in rows)
        compressed = gzip.compress(raw)
        (directory / migracao.DATA_FILE).write_bytes(compressed)
        manifest = dict(format_version=1, database='athlete_lab', table='telemetry',
                        columns=list(migracao.COLUMNS), rows=len(rows), file=migracao.DATA_FILE,
                        sha256=hashlib.sha256(compressed).hexdigest(),
                        content_sha256=hashlib.sha256(raw).hexdigest())
        atomic_json(directory / 'manifest.json', manifest)
        return manifest

    def row(self):
        return dict(id=1, received_at='2026-09-09T23:59:50.872', mqtt_username='lab-teste-01',
                    client_id='lab-teste-01', topic='atletas/lab-teste-01/telemetria', boot_id='teste',
                    sample_seq=1, source='test', accel_x_g=0.1, accel_y_g=0.2, accel_z_g=0.9,
                    payload={'source': 'test', 'bpm': None, 'distancia_km': 0.0})

    def test_normal_install_has_no_restore_or_database_connection(self):
        with tempfile.TemporaryDirectory() as folder, patch('migracao.connect') as connect:
            self.assertIsNone(migracao.restore_history(folder))
            self.assertTrue(network_enabled(folder))
            connect.assert_not_called()

    def test_portable_launcher_finds_child_lab_and_enables_network(self):
        with tempfile.TemporaryDirectory() as folder:
            lab = Path(folder) / 'laboratorio'
            lab.mkdir()
            (lab / 'compose.yaml').touch()
            (lab / 'config.example.json').touch()
            self.write_snapshot(lab, [self.row()])
            self.assertEqual(find_folder(Path(folder) / 'ABRIR PAINEL.exe'), lab)
            self.assertTrue(network_enabled(lab))

    def test_valid_snapshot_keeps_nulls_and_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            self.write_snapshot(folder, [self.row()])
            manifest, rows = migracao.load_history(folder)
            self.assertEqual(rows, [self.row()])
            self.assertEqual(manifest['rows'], 1)

    def test_corrupt_snapshot_rejected_before_database_access(self):
        with tempfile.TemporaryDirectory() as folder, patch('migracao.connect') as connect:
            self.write_snapshot(folder, [self.row()])
            with (Path(folder) / 'migracao' / migracao.DATA_FILE).open('ab') as file:
                file.write(b'corrompido')
            with self.assertRaises(migracao.MigrationError):
                migracao.restore_history(folder)
            connect.assert_not_called()

    def test_missing_file_duplicate_identity_and_invalid_path_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / 'migracao'
            directory.mkdir()
            with self.assertRaises(migracao.MigrationError):
                migracao.load_history(folder)
            self.write_snapshot(folder, [self.row(), dict(self.row(), id=2)])
            with self.assertRaises(migracao.MigrationError):
                migracao.load_history(folder)
            manifest = self.write_snapshot(folder, [self.row()])
            manifest['file'] = '../config.local.json'
            atomic_json(directory / 'manifest.json', manifest)
            with self.assertRaises(migracao.MigrationError):
                migracao.load_history(folder)


if __name__ == '__main__':
    unittest.main(verbosity=2)
