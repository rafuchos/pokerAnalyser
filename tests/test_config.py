"""Tests for US-016: External Configuration for Stats Targets.

Covers:
- TargetsConfig.get_default() — all expected stats present
- TargetsConfig.load() — missing file returns defaults
- TargetsConfig.load() — JSON content
- TargetsConfig.load() — YAML template (fallback parser)
- TargetsConfig.load() — partial override (deep merge)
- TargetsConfig.validate() — valid config
- TargetsConfig.validate() — bad range (low > high)
- TargetsConfig.validate() — warning narrower than healthy
- TargetsConfig.save_default() — creates YAML file
- _parse_yaml_fallback() — inline list, inline dict, comments
- _deep_merge() — nested merge
- CashAnalyzer config integration — classify methods use config ranges
- LeakFinder config integration — leak detection uses config ranges
- CLI config --init, config --validate, config (show)
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

from src.config import (
    TargetsConfig,
    _deep_merge,
    _parse_yaml_fallback,
    _default_data,
    DEFAULT_CONFIG_PATH,
)


# ── TargetsConfig.get_default ──────────────────────────────────────────────


class TestTargetsConfigDefault(unittest.TestCase):

    def setUp(self):
        self.cfg = TargetsConfig.get_default()

    def test_all_preflop_stats_present(self):
        for stat in ('vpip', 'pfr', 'three_bet', 'fold_to_3bet', 'ats'):
            self.assertIn(stat, self.cfg.healthy_ranges, f"Missing preflop stat: {stat}")
            self.assertIn(stat, self.cfg.warning_ranges, f"Missing warning range: {stat}")

    def test_all_postflop_stats_present(self):
        for stat in ('af', 'wtsd', 'wsd', 'cbet', 'fold_to_cbet', 'check_raise'):
            self.assertIn(stat, self.cfg.postflop_healthy_ranges, f"Missing postflop stat: {stat}")
            self.assertIn(stat, self.cfg.postflop_warning_ranges)

    def test_positional_vpip_all_positions(self):
        for pos in ('UTG', 'UTG+1', 'MP', 'MP+1', 'HJ', 'CO', 'BTN', 'SB', 'BB'):
            self.assertIn(pos, self.cfg.position_vpip_healthy, f"Missing vpip pos: {pos}")
            self.assertIn(pos, self.cfg.position_vpip_warning)

    def test_positional_pfr_all_positions(self):
        for pos in ('UTG', 'UTG+1', 'MP', 'MP+1', 'HJ', 'CO', 'BTN', 'SB', 'BB'):
            self.assertIn(pos, self.cfg.position_pfr_healthy, f"Missing pfr pos: {pos}")

    def test_ranges_are_tuples_of_length_2(self):
        for stat, rng in self.cfg.healthy_ranges.items():
            self.assertEqual(len(rng), 2, f"{stat} range length != 2")

    def test_healthy_low_lt_high(self):
        for stat, (low, high) in self.cfg.healthy_ranges.items():
            self.assertLess(low, high, f"preflop.{stat}: low >= high")
        for stat, (low, high) in self.cfg.postflop_healthy_ranges.items():
            self.assertLess(low, high, f"postflop.{stat}: low >= high")

    def test_warning_contains_healthy_preflop(self):
        for stat in self.cfg.healthy_ranges:
            h_low, h_high = self.cfg.healthy_ranges[stat]
            w_low, w_high = self.cfg.warning_ranges[stat]
            self.assertLessEqual(w_low, h_low, f"{stat}: warning low > healthy low")
            self.assertGreaterEqual(w_high, h_high, f"{stat}: warning high < healthy high")

    def test_vpip_defaults(self):
        self.assertEqual(self.cfg.healthy_ranges['vpip'], (22, 30))
        self.assertEqual(self.cfg.warning_ranges['vpip'], (18, 35))

    def test_af_defaults_float(self):
        h_low, h_high = self.cfg.postflop_healthy_ranges['af']
        self.assertAlmostEqual(h_low, 2.0)
        self.assertAlmostEqual(h_high, 3.5)

    def test_utg_vpip_tighter_than_btn(self):
        utg_high = self.cfg.position_vpip_healthy['UTG'][1]
        btn_low = self.cfg.position_vpip_healthy['BTN'][0]
        self.assertLess(utg_high, btn_low)


# ── TargetsConfig.load ─────────────────────────────────────────────────────


class TestTargetsConfigLoad(unittest.TestCase):

    def test_load_nonexistent_returns_defaults(self):
        cfg = TargetsConfig.load('/nonexistent/path/targets.yaml')
        default = TargetsConfig.get_default()
        self.assertEqual(cfg.healthy_ranges, default.healthy_ranges)
        self.assertEqual(cfg.postflop_healthy_ranges, default.postflop_healthy_ranges)

    def test_load_json_file(self):
        data = {
            'preflop': {
                'vpip': {'healthy': [20, 28], 'warning': [16, 33]},
            }
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                         delete=False) as fh:
            json.dump(data, fh)
            path = fh.name
        try:
            cfg = TargetsConfig.load(path)
            # vpip overridden
            self.assertEqual(cfg.healthy_ranges['vpip'], (20, 28))
            # pfr uses default (partial override)
            self.assertEqual(cfg.healthy_ranges['pfr'],
                             TargetsConfig.get_default().healthy_ranges['pfr'])
        finally:
            os.unlink(path)

    def test_load_yaml_template(self):
        """The generated YAML template must parse correctly."""
        from src.config import _default_yaml_template
        template = _default_yaml_template()
        data = _parse_yaml_fallback(template)
        cfg = TargetsConfig(data)
        default = TargetsConfig.get_default()
        self.assertEqual(cfg.healthy_ranges['vpip'], default.healthy_ranges['vpip'])
        self.assertEqual(cfg.postflop_healthy_ranges['af'],
                         default.postflop_healthy_ranges['af'])
        self.assertEqual(cfg.position_vpip_healthy['BTN'],
                         default.position_vpip_healthy['BTN'])

    def test_partial_override_changes_only_specified(self):
        """Only the specified values change; everything else stays default."""
        data = {'preflop': {'vpip': {'healthy': [19, 27], 'warning': [15, 32]}}}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                         delete=False) as fh:
            json.dump(data, fh)
            path = fh.name
        try:
            cfg = TargetsConfig.load(path)
            self.assertEqual(cfg.healthy_ranges['vpip'], (19, 27))
            # pfr unchanged
            default_pfr = TargetsConfig.get_default().healthy_ranges['pfr']
            self.assertEqual(cfg.healthy_ranges['pfr'], default_pfr)
            # postflop unchanged
            default_af = TargetsConfig.get_default().postflop_healthy_ranges['af']
            self.assertEqual(cfg.postflop_healthy_ranges['af'], default_af)
        finally:
            os.unlink(path)

    def test_load_json_fallback_from_yaml_path(self):
        """If .yaml not found but .json exists, loads .json instead."""
        data = {'preflop': {'vpip': {'healthy': [21, 29], 'warning': [17, 34]}}}
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, 'targets.json')
            with open(json_path, 'w') as fh:
                json.dump(data, fh)
            yaml_path = os.path.join(tmpdir, 'targets.yaml')
            # yaml_path doesn't exist; json_path does
            cfg = TargetsConfig.load(yaml_path)
            self.assertEqual(cfg.healthy_ranges['vpip'], (21, 29))

    def test_load_invalid_json_raises(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                         delete=False) as fh:
            fh.write('{ NOT VALID JSON }')
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                TargetsConfig.load(path)
        finally:
            os.unlink(path)


# ── TargetsConfig.validate ─────────────────────────────────────────────────


class TestTargetsConfigValidate(unittest.TestCase):

    def test_default_config_is_valid(self):
        errors = TargetsConfig.get_default().validate()
        self.assertEqual(errors, [], f"Default config has errors: {errors}")

    def test_bad_range_low_equals_high(self):
        data = _default_data()
        data['preflop']['vpip']['healthy'] = [25, 25]
        cfg = TargetsConfig(data)
        errors = cfg.validate()
        self.assertTrue(any('vpip' in e for e in errors))

    def test_bad_range_low_greater_than_high(self):
        data = _default_data()
        data['preflop']['vpip']['healthy'] = [30, 20]
        cfg = TargetsConfig(data)
        errors = cfg.validate()
        self.assertTrue(any('vpip' in e for e in errors))

    def test_warning_narrower_than_healthy_is_error(self):
        data = _default_data()
        # Warning [23, 29] is INSIDE healthy [22, 30] — should be flagged
        data['preflop']['vpip']['warning'] = [23, 29]
        cfg = TargetsConfig(data)
        errors = cfg.validate()
        self.assertTrue(any('vpip' in e for e in errors))

    def test_valid_custom_config_no_errors(self):
        data = _default_data()
        data['preflop']['vpip']['healthy'] = [20, 28]
        data['preflop']['vpip']['warning'] = [15, 35]
        cfg = TargetsConfig(data)
        errors = cfg.validate()
        # vpip section should be fine now
        vpip_errors = [e for e in errors if 'vpip' in e]
        self.assertEqual(vpip_errors, [])

    def test_postflop_warning_narrower_than_healthy(self):
        data = _default_data()
        data['postflop']['af']['warning'] = [2.5, 3.0]  # inside healthy [2.0, 3.5]
        cfg = TargetsConfig(data)
        errors = cfg.validate()
        self.assertTrue(any('af' in e for e in errors))


# ── save_default ───────────────────────────────────────────────────────────


class TestTargetsConfigSave(unittest.TestCase):

    def test_save_default_yaml_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'targets.yaml')
            TargetsConfig.save_default(path)
            self.assertTrue(os.path.exists(path))
            with open(path) as fh:
                content = fh.read()
            self.assertIn('vpip', content)
            self.assertIn('healthy', content)

    def test_save_default_json_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'targets.json')
            TargetsConfig.save_default(path)
            self.assertTrue(os.path.exists(path))
            with open(path) as fh:
                data = json.load(fh)
            self.assertIn('preflop', data)
            self.assertIn('vpip', data['preflop'])

    def test_save_and_reload_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'targets.yaml')
            TargetsConfig.save_default(path)
            cfg = TargetsConfig.load(path)
            default = TargetsConfig.get_default()
            self.assertEqual(cfg.healthy_ranges, default.healthy_ranges)
            self.assertEqual(cfg.postflop_healthy_ranges,
                             default.postflop_healthy_ranges)

    def test_save_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'a', 'b', 'targets.yaml')
            TargetsConfig.save_default(path)
            self.assertTrue(os.path.exists(path))


# ── _parse_yaml_fallback ───────────────────────────────────────────────────


class TestParseYamlFallback(unittest.TestCase):

    def test_simple_mapping(self):
        yaml = "key: value\nnum: 42\n"
        result = _parse_yaml_fallback(yaml)
        self.assertEqual(result['key'], 'value')
        self.assertEqual(result['num'], 42)

    def test_nested_mapping(self):
        yaml = "outer:\n  inner: 10\n"
        result = _parse_yaml_fallback(yaml)
        self.assertEqual(result['outer']['inner'], 10)

    def test_inline_list(self):
        yaml = "vpip:\n  healthy: [22, 30]\n"
        result = _parse_yaml_fallback(yaml)
        self.assertEqual(result['vpip']['healthy'], [22, 30])

    def test_inline_dict(self):
        yaml = "UTG: {healthy: [12, 18], warning: [9, 24]}\n"
        result = _parse_yaml_fallback(yaml)
        self.assertEqual(result['UTG']['healthy'], [12, 18])
        self.assertEqual(result['UTG']['warning'], [9, 24])

    def test_comment_ignored(self):
        yaml = "# This is a comment\nvpip: 25  # inline comment\n"
        result = _parse_yaml_fallback(yaml)
        self.assertEqual(result['vpip'], 25)

    def test_float_value(self):
        yaml = "af:\n  healthy: [2.0, 3.5]\n"
        result = _parse_yaml_fallback(yaml)
        h = result['af']['healthy']
        self.assertAlmostEqual(h[0], 2.0)
        self.assertAlmostEqual(h[1], 3.5)

    def test_quoted_version(self):
        yaml = 'version: "1.0"\n'
        result = _parse_yaml_fallback(yaml)
        self.assertEqual(result['version'], '1.0')

    def test_inline_list_with_trailing_comment(self):
        yaml = "  healthy: [22, 30]    # ideal range\n"
        result = _parse_yaml_fallback(yaml)
        self.assertEqual(result['healthy'], [22, 30])

    def test_position_keys_with_plus(self):
        yaml = "  UTG+1: {healthy: [13, 20], warning: [10, 26]}\n"
        result = _parse_yaml_fallback(yaml)
        self.assertIn('UTG+1', result)
        self.assertEqual(result['UTG+1']['healthy'], [13, 20])

    def test_full_template_parses(self):
        from src.config import _default_yaml_template
        result = _parse_yaml_fallback(_default_yaml_template())
        self.assertIn('preflop', result)
        self.assertIn('postflop', result)
        self.assertIn('positions', result)
        self.assertIn('vpip', result['preflop'])
        self.assertEqual(result['preflop']['vpip']['healthy'], [22, 30])


# ── _deep_merge ────────────────────────────────────────────────────────────


class TestDeepMerge(unittest.TestCase):

    def test_override_scalar(self):
        base = {'a': 1, 'b': 2}
        override = {'a': 99}
        result = _deep_merge(base, override)
        self.assertEqual(result['a'], 99)
        self.assertEqual(result['b'], 2)

    def test_nested_override(self):
        base = {'x': {'y': 1, 'z': 2}}
        override = {'x': {'y': 99}}
        result = _deep_merge(base, override)
        self.assertEqual(result['x']['y'], 99)
        self.assertEqual(result['x']['z'], 2)

    def test_add_new_key(self):
        base = {'a': 1}
        override = {'b': 2}
        result = _deep_merge(base, override)
        self.assertIn('a', result)
        self.assertIn('b', result)

    def test_base_unchanged(self):
        base = {'a': {'x': 1}}
        override = {'a': {'x': 99}}
        _deep_merge(base, override)
        self.assertEqual(base['a']['x'], 1)  # original not mutated


# ── CashAnalyzer config integration ───────────────────────────────────────


class TestCashAnalyzerWithConfig(unittest.TestCase):

    def _make_analyzer_with_config(self, healthy_vpip, warning_vpip):
        """Return a CashAnalyzer instance with a custom vpip range."""
        import sqlite3
        from src.db.schema import init_db
        from src.db.repository import Repository
        from src.config import _default_data

        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        repo = Repository(conn)

        data = _default_data()
        data['preflop']['vpip']['healthy'] = list(healthy_vpip)
        data['preflop']['vpip']['warning'] = list(warning_vpip)
        config = TargetsConfig(data)

        from src.analyzers.cash import CashAnalyzer
        return CashAnalyzer(repo, config=config)

    def test_classify_health_uses_config_healthy_range(self):
        """Value inside custom healthy range → 'good'."""
        analyzer = self._make_analyzer_with_config((10, 20), (5, 25))
        # 15 is inside custom healthy [10, 20]
        result = analyzer._classify_health('vpip', 15.0)
        self.assertEqual(result, 'good')

    def test_classify_health_uses_config_warning_range(self):
        """Value in custom warning but outside healthy → 'warning'."""
        analyzer = self._make_analyzer_with_config((10, 20), (5, 25))
        # 7 is inside warning [5, 25] but outside healthy [10, 20]
        result = analyzer._classify_health('vpip', 7.0)
        self.assertEqual(result, 'warning')

    def test_classify_health_uses_config_danger(self):
        """Value outside custom warning → 'danger'."""
        analyzer = self._make_analyzer_with_config((10, 20), (5, 25))
        # 30 is outside warning [5, 25]
        result = analyzer._classify_health('vpip', 30.0)
        self.assertEqual(result, 'danger')

    def test_class_method_still_uses_original_ranges(self):
        """Class-level _classify_health is unchanged (backward compat)."""
        from src.analyzers.cash import CashAnalyzer
        # Default healthy vpip is [22, 30]; 25 should be 'good'
        self.assertEqual(CashAnalyzer._classify_health('vpip', 25.0), 'good')
        # 19 is inside default warning [18, 35] but outside healthy [22, 30]
        self.assertEqual(CashAnalyzer._classify_health('vpip', 19.0), 'warning')
        # 15 is below default warning [18, 35] → 'danger'
        self.assertEqual(CashAnalyzer._classify_health('vpip', 15.0), 'danger')

    def test_classify_postflop_uses_config(self):
        """Custom postflop AF range used by instance."""
        import sqlite3
        from src.db.schema import init_db
        from src.db.repository import Repository
        from src.config import _default_data
        from src.analyzers.cash import CashAnalyzer

        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        repo = Repository(conn)

        data = _default_data()
        data['postflop']['af']['healthy'] = [1.0, 2.0]  # override default [2.0, 3.5]
        data['postflop']['af']['warning'] = [0.5, 2.5]
        config = TargetsConfig(data)
        analyzer = CashAnalyzer(repo, config=config)

        # 1.5 is inside new healthy [1.0, 2.0]
        self.assertEqual(analyzer._classify_postflop_health('af', 1.5), 'good')
        # 2.5 is in warning [0.5, 2.5] but outside healthy [1.0, 2.0]
        self.assertEqual(analyzer._classify_postflop_health('af', 2.5), 'warning')

    def test_classify_positional_uses_config(self):
        """Custom per-position vpip range used by instance."""
        import sqlite3
        from src.db.schema import init_db
        from src.db.repository import Repository
        from src.config import _default_data
        from src.analyzers.cash import CashAnalyzer

        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        repo = Repository(conn)

        data = _default_data()
        data['positions']['vpip']['UTG'] = {'healthy': [5, 10], 'warning': [3, 12]}
        config = TargetsConfig(data)
        analyzer = CashAnalyzer(repo, config=config)

        # 7 inside new healthy [5, 10]
        self.assertEqual(analyzer._classify_positional_health('vpip', 'UTG', 7.0), 'good')
        # 15 outside warning [3, 12]
        self.assertEqual(analyzer._classify_positional_health('vpip', 'UTG', 15.0), 'danger')

    def test_no_config_uses_class_defaults(self):
        """Instance without config uses class-level defaults."""
        import sqlite3
        from src.db.schema import init_db
        from src.db.repository import Repository
        from src.analyzers.cash import CashAnalyzer

        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        repo = Repository(conn)
        analyzer = CashAnalyzer(repo)

        # 25 is inside default healthy [22, 30]
        self.assertEqual(analyzer._classify_health('vpip', 25.0), 'good')
        self.assertIs(analyzer._healthy_ranges,
                      CashAnalyzer.HEALTHY_RANGES)

    def test_instance_ranges_expose_custom_values(self):
        """_healthy_ranges instance attr reflects config."""
        import sqlite3
        from src.db.schema import init_db
        from src.db.repository import Repository
        from src.config import _default_data
        from src.analyzers.cash import CashAnalyzer

        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        repo = Repository(conn)

        data = _default_data()
        data['preflop']['vpip']['healthy'] = [19, 27]
        config = TargetsConfig(data)
        analyzer = CashAnalyzer(repo, config=config)

        self.assertEqual(analyzer._healthy_ranges['vpip'], (19, 27))
        # Class attribute unchanged
        self.assertEqual(CashAnalyzer.HEALTHY_RANGES['vpip'], (22, 30))


# ── LeakFinder config integration ─────────────────────────────────────────


class TestLeakFinderWithConfig(unittest.TestCase):

    def _setup(self):
        import sqlite3
        from src.db.schema import init_db
        from src.db.repository import Repository
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        return conn, Repository(conn)

    def test_leakfinder_uses_custom_healthy_ranges(self):
        """With a tighter custom vpip range, a normal value becomes a leak."""
        from src.config import _default_data
        from src.analyzers.cash import CashAnalyzer
        from src.analyzers.leak_finder import LeakFinder

        _, repo = self._setup()

        data = _default_data()
        # Make vpip healthy very tight: [24, 26] (value 22 would be a leak)
        data['preflop']['vpip']['healthy'] = [24, 26]
        data['preflop']['vpip']['warning'] = [22, 28]
        config = TargetsConfig(data)

        analyzer = CashAnalyzer(repo, config=config)
        leak_finder = LeakFinder(analyzer, repo)

        # Simulate a preflop stats dict with vpip=20 (outside warning [22, 28])
        overall = {
            'vpip': 20.0, 'pfr': 20.0, 'three_bet': 9.0,
            'fold_to_3bet': 48.0, 'ats': 37.0, 'total_hands': 200,
        }
        leaks = leak_finder._detect_preflop_leaks(overall)
        vpip_leaks = [l for l in leaks if l.stat_name == 'vpip']
        self.assertGreater(len(vpip_leaks), 0, "vpip=20 should be a leak with tight healthy [24,26]")
        self.assertEqual(vpip_leaks[0].direction, 'too_low')

    def test_leakfinder_no_leak_within_custom_range(self):
        """Value inside custom healthy range → no leak for that stat."""
        from src.config import _default_data
        from src.analyzers.cash import CashAnalyzer
        from src.analyzers.leak_finder import LeakFinder

        _, repo = self._setup()

        data = _default_data()
        # Very wide healthy range — nothing should be a leak
        data['preflop']['vpip']['healthy'] = [10, 45]
        data['preflop']['vpip']['warning'] = [5, 50]
        config = TargetsConfig(data)

        analyzer = CashAnalyzer(repo, config=config)
        leak_finder = LeakFinder(analyzer, repo)

        overall = {'vpip': 30.0, 'pfr': 20.0, 'three_bet': 9.0,
                   'fold_to_3bet': 48.0, 'ats': 37.0, 'total_hands': 200}
        leaks = leak_finder._detect_preflop_leaks(overall)
        vpip_leaks = [l for l in leaks if l.stat_name == 'vpip']
        self.assertEqual(len(vpip_leaks), 0)

    def test_leakfinder_default_ranges_unchanged(self):
        """Without config, leak finder uses class-level defaults."""
        from src.analyzers.cash import CashAnalyzer
        from src.analyzers.leak_finder import LeakFinder

        _, repo = self._setup()
        analyzer = CashAnalyzer(repo)
        leak_finder = LeakFinder(analyzer, repo)

        # vpip=10 is well below default healthy [22, 30] → should be a leak
        overall = {'vpip': 10.0, 'pfr': 20.0, 'three_bet': 9.0,
                   'fold_to_3bet': 48.0, 'ats': 37.0, 'total_hands': 200}
        leaks = leak_finder._detect_preflop_leaks(overall)
        vpip_leaks = [l for l in leaks if l.stat_name == 'vpip']
        self.assertEqual(len(vpip_leaks), 1)
        self.assertEqual(vpip_leaks[0].direction, 'too_low')

    def test_leakfinder_positional_uses_custom_range(self):
        """Custom per-position range is used by _detect_positional_leaks."""
        from src.config import _default_data
        from src.analyzers.cash import CashAnalyzer
        from src.analyzers.leak_finder import LeakFinder

        _, repo = self._setup()

        data = _default_data()
        # Override CO vpip healthy to [15, 20] (default is [22, 30])
        data['positions']['vpip']['CO'] = {'healthy': [15, 20], 'warning': [12, 23]}
        config = TargetsConfig(data)

        analyzer = CashAnalyzer(repo, config=config)
        leak_finder = LeakFinder(analyzer, repo)

        by_position = {
            'CO': {'total_hands': 30, 'vpip': 25.0, 'pfr': 20.0}
        }
        leaks = leak_finder._detect_positional_leaks(by_position)
        co_vpip_leaks = [l for l in leaks if l.stat_name == 'vpip' and l.position == 'CO']
        self.assertGreater(len(co_vpip_leaks), 0)
        self.assertEqual(co_vpip_leaks[0].direction, 'too_high')


# ── CLI integration ────────────────────────────────────────────────────────


class TestConfigCLI(unittest.TestCase):

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, 'main.py', *args],
            capture_output=True, text=True, cwd='/workspaces/CashHandTracking'
        )

    def test_config_help(self):
        result = self._run('config', '--help')
        self.assertEqual(result.returncode, 0)
        self.assertIn('--init', result.stdout)
        self.assertIn('--validate', result.stdout)

    def test_config_init_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'targets.yaml')
            result = self._run('config', '--init', '--path', path)
            self.assertEqual(result.returncode, 0)
            self.assertIn('written', result.stdout)
            self.assertTrue(os.path.exists(path))

    def test_config_init_does_not_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'targets.yaml')
            # Create it first
            self._run('config', '--init', '--path', path)
            # Try again without --force
            result = self._run('config', '--init', '--path', path)
            self.assertEqual(result.returncode, 0)
            self.assertIn('already exists', result.stdout)

    def test_config_init_force_overwrites(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'targets.yaml')
            self._run('config', '--init', '--path', path)
            result = self._run('config', '--init', '--force', '--path', path)
            self.assertEqual(result.returncode, 0)
            self.assertIn('written', result.stdout)

    def test_config_validate_default_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'targets.yaml')
            self._run('config', '--init', '--path', path)
            result = self._run('config', '--validate', '--path', path)
            self.assertEqual(result.returncode, 0)
            self.assertIn('valid', result.stdout)

    def test_config_validate_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                         delete=False) as fh:
            fh.write('{ NOT JSON }')
            path = fh.name
        try:
            result = self._run('config', '--validate', '--path', path)
            self.assertEqual(result.returncode, 0)
            self.assertIn('error', result.stdout.lower())
        finally:
            os.unlink(path)

    def test_config_show_uses_defaults_when_no_file(self):
        result = self._run('config', '--path', '/nonexistent/targets.yaml')
        self.assertEqual(result.returncode, 0)
        self.assertIn('CURRENT STATS TARGETS', result.stdout)
        self.assertIn('vpip', result.stdout)

    def test_main_help_includes_config(self):
        result = self._run('--help')
        self.assertEqual(result.returncode, 0)
        self.assertIn('config', result.stdout)


if __name__ == '__main__':
    unittest.main()
