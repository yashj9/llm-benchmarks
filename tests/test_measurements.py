import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('measurements', Path(__file__).resolve().parents[1] / 'scripts/measurements.py')
measurements = importlib.util.module_from_spec(spec)
spec.loader.exec_module(measurements)


class PrefillTests(unittest.TestCase):
    def test_pairs_are_labeled_without_claiming_verified_cache(self):
        self.assertTrue(callable(getattr(measurements, 'prefill', None)), 'Prefill support missing')
        pair = [dict(label='fresh_prefix', prompt_tokens=12000, prompt_tps=4000, ttft_s=3, cache_verified=False, content='PRIVATE'),
                dict(label='repeat_same_prefix', prompt_tokens=12000, prompt_tps=60000, ttft_s=0.2, cache_verified=False, content='PRIVATE')]
        result = measurements.prefill(pair)
        self.assertEqual(result['cold_tps'], 4000)
        self.assertEqual(result['hot_tps'], 60000)
        self.assertEqual(result['hot_ttft_s'], 0.2)
        self.assertEqual(result['prompt_tokens'], 12000)
        self.assertFalse(result['hot_cache_verified'])
        self.assertNotIn('PRIVATE', str(result))


class ResourceTests(unittest.TestCase):
    def test_resource_window_excludes_retry_and_does_not_include_igpu(self):
        self.assertTrue(callable(getattr(measurements, 'resources', None)), 'Resource summarizer missing')
        sample = {'timestamp': 20, 'gpu_used_mib': [1024, 2048], 'windows_ram_used_mb': 32768,
                  'lhm': {'cpu': {'package_power_w': 20, 'utilization_pct': 30}, 'gpus': [
                      {'name': 'NVIDIA GeForce RTX 5090', 'power_w': 100, 'utilization_pct': 80, 'temperature_c': 60},
                      {'name': 'NVIDIA GeForce RTX 5060 Ti', 'power_w': 50, 'utilization_pct': 40, 'temperature_c': 45},
                      {'name': 'AMD Radeon Graphics', 'power_w': 9999}]}}
        retry = {**sample, 'timestamp': 1, 'windows_ram_used_mb': 999999}
        r = measurements.resources([retry, sample], start=10, end=30, ram_total_gib=64)
        self.assertEqual(r['samples'], 1)
        self.assertEqual(r['ram_peak_gib'], 32)
        self.assertEqual(r['ram_available_min_gib'], 32)
        self.assertEqual(r['gpu0_vram_peak_gib'], 1)
        self.assertEqual(r['gpu1_vram_peak_gib'], 2)
        self.assertEqual(r['cpu_mean_pct'], 30)
        self.assertEqual(r['cpu_gpu_mean_w'], sum([20, 100, 50]))
        self.assertIsNone(r['cpu_temp_peak_c'])
        self.assertIsNone(r['swap_peak_gib'])


    def test_pool_keeps_peaks_separate_from_median_session_means(self):
        self.assertTrue(callable(getattr(measurements, 'pool', None)), 'Pooling missing')
        a={'samples':2,'ram_peak_gib':20,'cpu_mean_w':80,'cpu_temp_peak_c':None}
        b={'samples':3,'ram_peak_gib':30,'cpu_mean_w':120,'cpu_temp_peak_c':70}
        r=measurements.pool([a,b])
        self.assertEqual(r['ram_peak_gib'], max([20,30]))
        import statistics
        self.assertEqual(r['cpu_mean_w'], statistics.median([80,120]))
        self.assertEqual(r['cpu_temp_peak_c'], 70)
        self.assertEqual(r['samples'], sum([2,3]))
        self.assertEqual(r['measured_sessions'], 2)


if __name__ == '__main__':
    unittest.main()
