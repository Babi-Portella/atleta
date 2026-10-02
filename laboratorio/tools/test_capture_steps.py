import unittest
from capture_steps import parse_sample, parse_mqtt_samples, summarize, parse_trace_begin, samples_since_start


class CaptureTests(unittest.TestCase):
    def test_only_diagnostic_samples_are_saved(self):
        self.assertIsNone(parse_sample('TELEMETRY {"passos":7}'))
        row = parse_sample('IMU_SAMPLE 100,0,0,1,0,0,0,.15,500,0,7,5,1')
        self.assertEqual(row['steps'], 5)
        self.assertEqual(row['event'], 7)
        for line in ('IMU_SAMPLE 1,2',
                     'IMU_SAMPLE 100,nan,0,1,0,0,0,.15,500,0,7,5,1',
                     'IMU_SAMPLE 100,0,0,1,0,0,0,.15,500,0,99,5,1'):
            with self.assertRaises(ValueError):
                parse_sample(line)

    def test_wraparound_and_reset_do_not_produce_fake_accuracy(self):
        def row(ms, steps, active=1):
            return {'ms': ms, 'steps': steps, 'event': 0, 'active': active}
        report = summarize([row(0xfffffff0, 5), row(4, 7)], 2, 0, 5)
        self.assertEqual(report['median_sample_interval_ms'], 20)
        self.assertEqual(report['counted_steps'], 2)
        self.assertEqual(report['count_error'], -3)
        report = summarize([row(100, 7), row(120, 0, 0)], 0, 0, 5)
        self.assertIsNone(report['counted_steps'])
        self.assertIsNone(report['count_error'])
        self.assertEqual(report['session_resets'], 1)
        self.assertEqual(report['paused_samples'], 1)

    def test_wifi_units_and_schema(self):
        self.assertEqual(parse_mqtt_samples({'passos': 7}), [])
        payload = {'imu_trace_schema': 2,
                   'imu_trace': [[100, -2500, 5000, 10000, 1234, -250, 0, 1500, 500, 0, 7, 5, 1]]}
        row = parse_mqtt_samples(payload)[0]
        self.assertEqual(row['ax_g'], -.25)
        self.assertEqual(row['gx_dps'], 12.34)
        self.assertEqual(row['gy_dps'], -2.5)
        self.assertEqual(row['filtered_g'], .15)
        self.assertEqual(row['steps'], 5)
        payload['imu_trace_schema'] = 99
        with self.assertRaises(ValueError):
            parse_mqtt_samples(payload)

    def test_paused_samples_do_not_repeat_previous_detector_decision(self):
        rows = [
            {'ms': 100, 'steps': 5, 'event': 7, 'active': 1},
            {'ms': 120, 'steps': 5, 'event': 7, 'active': 0},
            {'ms': 140, 'steps': 5, 'event': 7, 'active': 0},
        ]
        report = summarize(rows, 0, 0, None)
        self.assertEqual(report['detector_events'], {'counted': 1})
        self.assertEqual(report['counted_steps'], 0)
        self.assertEqual(report['paused_samples'], 2)

    def test_session_change_invalidates_count_even_when_counter_does_not_fall(self):
        rows = [{'ms': 100, 'steps': 0, 'event': 0, 'active': 1},
                {'ms': 120, 'steps': 0, 'event': 0, 'active': 1}]
        report = summarize(rows, 0, 0, 0, session_changes=1)
        self.assertIsNone(report['counted_steps'])
        self.assertIsNone(report['count_error'])
        self.assertEqual(report['session_id_changes'], 1)

    def test_requested_duration_must_fit_firmware_timeout(self):
        old = 'IMU_TRACE_BEGIN schema=2 transport=mqtt rate_hz=50 timeout_s=120'
        self.assertEqual(parse_trace_begin(old, 110), (120, None))
        with self.assertRaises(ValueError):
            parse_trace_begin(old, 580)
        new = old.replace('timeout_s=120', 'timeout_s=600 start_ms=1000')
        self.assertEqual(parse_trace_begin(new, 580), (600, 1000))

    def test_packets_queued_before_command_are_excluded_across_clock_wrap(self):
        rows = [{'ms': 0xfffffff0}, {'ms': 4}, {'ms': 30}, {'ms': 610000}]
        self.assertEqual(samples_since_start(rows, 0xfffffff5, 600), rows[1:3])
        self.assertEqual(samples_since_start(rows, None, 120), rows)


if __name__ == '__main__':
    unittest.main()
