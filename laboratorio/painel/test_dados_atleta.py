import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pymysql
from dados_atleta import fetch_readings, metric_values, duration, freshness, DataError
from rede import atomic_json


class AthleteDataTests(unittest.TestCase):
    def test_unavailable_is_distinct_from_real_zero(self):
        empty = metric_values({})
        self.assertTrue(all(v == 'Indisponível' for v in empty.values()))
        values = metric_values({'passos': 0, 'duracao_s': 0, 'battery_percent_estimate': 0,
                                'latitude': 0, 'longitude': 0, 'distancia_km': None, 'bpm': float('nan')})
        self.assertEqual(values['passos'], '0')
        self.assertEqual(values['tempo'], '00:00:00')
        self.assertEqual(values['bateria'], '0%')
        self.assertEqual(values['gps'], '0.00000, 0.00000')
        self.assertEqual(values['distancia'], 'Indisponível')
        self.assertEqual(values['bpm'], 'Indisponível')

    def test_formats_time_decimal_comma_and_rejects_non_numbers(self):
        self.assertEqual(duration(3661), '01:01:01')
        self.assertEqual(duration(True), 'Indisponível')
        values = metric_values({'distancia_km': 1.125, 'calorias_kcal': 2.34, 'bpm': '90'})
        self.assertEqual(values['distancia'], '1,125 km')
        self.assertEqual(values['calorias'], '2,3 kcal')
        self.assertEqual(values['bpm'], 'Indisponível')

    def test_old_reading_is_not_live(self):
        self.assertEqual(freshness(10)[0], 'Recebendo dados')
        self.assertIn('Sem dados recentes', freshness(11)[0])

    def test_query_filters_authenticated_device_and_real_source(self):
        with tempfile.TemporaryDirectory() as folder:
            atomic_json(Path(folder)/'runtime/settings.json', {'mysql_port': 33070})
            atomic_json(Path(folder)/'runtime/secrets.json', {'mysql_reader': 'test-reader-only', 'dashboard': 'not-for-query'})
            cursor = MagicMock()
            cursor.fetchall.return_value = [{'id': 1, 'received_at': datetime(2026, 9, 9, 23, 45),
                                              'age_seconds': 1.5, 'payload': json.dumps({'passos': 0})}]
            connection = MagicMock()
            connection.__enter__.return_value.cursor.return_value.__enter__.return_value = cursor
            with patch('dados_atleta.pymysql.connect', return_value=connection) as connect:
                rows = fetch_readings(folder)
            self.assertEqual(rows[0]['payload']['passos'], 0)
            self.assertEqual(rows[0]['received_at'].tzinfo, timezone.utc)
            self.assertEqual(connect.call_args.kwargs['user'], 'lab_reader')
            self.assertEqual(connect.call_args.kwargs['host'], '127.0.0.1')
            self.assertEqual(connect.call_args.kwargs['password'], 'test-reader-only')
            sql, params = cursor.execute.call_args.args
            self.assertIn('mqtt_username=%s AND source=%s', sql)
            self.assertEqual(params, ('m5-atleta-01', 'device', 120))
            self.assertTrue(sql.lstrip().startswith('SELECT'))

    def test_no_preparation_does_not_attempt_database(self):
        with tempfile.TemporaryDirectory() as folder, patch('dados_atleta.pymysql.connect') as connect:
            with self.assertRaisesRegex(DataError, 'Inicie o laboratório'):
                fetch_readings(folder)
            connect.assert_not_called()

    def test_database_errors_do_not_expose_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            atomic_json(Path(folder)/'runtime/settings.json', {'mysql_port': 33070})
            atomic_json(Path(folder)/'runtime/secrets.json', {'mysql_reader': 'PRIVATE_VALUE'})
            with patch('dados_atleta.pymysql.connect', side_effect=pymysql.OperationalError('PRIVATE_VALUE')):
                with self.assertRaises(DataError) as error:
                    fetch_readings(folder)
                self.assertNotIn('PRIVATE_VALUE', str(error.exception))


if __name__ == '__main__':
    unittest.main()
