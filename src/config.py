"""External configuration for poker stats targets.

Loads from config/targets.yaml (or config/targets.json) if present,
falling back to hardcoded defaults for backward compatibility.

Usage:
    from src.config import TargetsConfig
    config = TargetsConfig.load()          # load from default path
    config = TargetsConfig.get_default()   # always use defaults
    config.validate()                       # list of error strings
    TargetsConfig.save_default('config/targets.yaml')  # write default file
"""

import json
import os

DEFAULT_CONFIG_PATH = 'config/targets.yaml'


class TargetsConfig:
    """External stats targets configuration for poker analysis.

    Attributes (all are dicts keyed by stat name or position):
        healthy_ranges         - preflop healthy (low, high) tuples
        warning_ranges         - preflop warning (low, high) tuples
        postflop_healthy_ranges
        postflop_warning_ranges
        position_vpip_healthy  - per-position VPIP healthy (low, high)
        position_vpip_warning
        position_pfr_healthy   - per-position PFR healthy (low, high)
        position_pfr_warning
    """

    def __init__(self, data: dict):
        self._data = data
        self._build()

    def _build(self) -> None:
        """Build typed range dicts from the raw config data dict."""
        preflop = self._data.get('preflop', {})
        postflop = self._data.get('postflop', {})
        positions = self._data.get('positions', {})

        self.healthy_ranges: dict = {}
        self.warning_ranges: dict = {}
        self.postflop_healthy_ranges: dict = {}
        self.postflop_warning_ranges: dict = {}
        self.position_vpip_healthy: dict = {}
        self.position_vpip_warning: dict = {}
        self.position_pfr_healthy: dict = {}
        self.position_pfr_warning: dict = {}

        for stat, vals in preflop.items():
            if not isinstance(vals, dict):
                continue
            h = vals.get('healthy')
            w = vals.get('warning')
            if h:
                self.healthy_ranges[stat] = tuple(h)
            if w:
                self.warning_ranges[stat] = tuple(w)

        for stat, vals in postflop.items():
            if not isinstance(vals, dict):
                continue
            h = vals.get('healthy')
            w = vals.get('warning')
            if h:
                self.postflop_healthy_ranges[stat] = tuple(h)
            if w:
                self.postflop_warning_ranges[stat] = tuple(w)

        for pos, vals in positions.get('vpip', {}).items():
            if not isinstance(vals, dict):
                continue
            h = vals.get('healthy')
            w = vals.get('warning')
            if h:
                self.position_vpip_healthy[pos] = tuple(h)
            if w:
                self.position_vpip_warning[pos] = tuple(w)

        for pos, vals in positions.get('pfr', {}).items():
            if not isinstance(vals, dict):
                continue
            h = vals.get('healthy')
            w = vals.get('warning')
            if h:
                self.position_pfr_healthy[pos] = tuple(h)
            if w:
                self.position_pfr_warning[pos] = tuple(w)

    # ── Loading ─────────────────────────────────────────────────────

    @classmethod
    def load(cls, path: str = DEFAULT_CONFIG_PATH) -> 'TargetsConfig':
        """Load config from file (YAML or JSON).

        Falls back to defaults if the file does not exist.
        Supports partial override: only specify the values you want to
        change; the rest use hardcoded defaults.
        """
        resolved = path
        if not os.path.exists(resolved):
            # Try JSON variant
            json_path = resolved.replace('.yaml', '.json').replace('.yml', '.json')
            if json_path != resolved and os.path.exists(json_path):
                resolved = json_path
            else:
                return cls.get_default()

        with open(resolved, encoding='utf-8') as fh:
            content = fh.read()

        try:
            if resolved.endswith(('.yaml', '.yml')):
                data = _parse_yaml(content)
            else:
                data = json.loads(content)
        except Exception as exc:
            raise ValueError(
                f"Failed to parse config file '{resolved}': {exc}"
            ) from exc

        # Deep-merge with defaults so partial overrides work
        merged = _deep_merge(_default_data(), data)
        return cls(merged)

    @classmethod
    def get_default(cls) -> 'TargetsConfig':
        """Return a TargetsConfig with the hardcoded defaults."""
        return cls(_default_data())

    # ── Validation ──────────────────────────────────────────────────

    def validate(self) -> list:
        """Validate configuration ranges.

        Returns a list of error strings (empty list = valid).
        """
        errors = []

        range_groups = [
            ('preflop.healthy', self.healthy_ranges),
            ('preflop.warning', self.warning_ranges),
            ('postflop.healthy', self.postflop_healthy_ranges),
            ('postflop.warning', self.postflop_warning_ranges),
        ]
        for label, rdict in range_groups:
            for stat, rng in rdict.items():
                if not isinstance(rng, (list, tuple)) or len(rng) != 2:
                    errors.append(f"{label}.{stat}: must be a [low, high] pair")
                    continue
                low, high = rng
                if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
                    errors.append(f"{label}.{stat}: values must be numeric")
                elif low >= high:
                    errors.append(
                        f"{label}.{stat}: low ({low}) must be less than high ({high})"
                    )

        # Warning ranges should be at least as wide as healthy ranges
        for stat in self.healthy_ranges:
            if stat in self.warning_ranges:
                h_low, h_high = self.healthy_ranges[stat]
                w_low, w_high = self.warning_ranges[stat]
                if w_low > h_low or w_high < h_high:
                    errors.append(
                        f"preflop.{stat}: warning [{w_low}, {w_high}] "
                        f"should contain healthy [{h_low}, {h_high}]"
                    )

        for stat in self.postflop_healthy_ranges:
            if stat in self.postflop_warning_ranges:
                h_low, h_high = self.postflop_healthy_ranges[stat]
                w_low, w_high = self.postflop_warning_ranges[stat]
                if w_low > h_low or w_high < h_high:
                    errors.append(
                        f"postflop.{stat}: warning [{w_low}, {w_high}] "
                        f"should contain healthy [{h_low}, {h_high}]"
                    )

        return errors

    # ── Saving ──────────────────────────────────────────────────────

    @staticmethod
    def save_default(path: str = DEFAULT_CONFIG_PATH) -> None:
        """Write the default config template to *path*.

        Creates parent directories if needed.
        Generates YAML for .yaml/.yml paths, JSON otherwise.
        """
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        if path.endswith(('.yaml', '.yml')):
            content = _default_yaml_template()
        else:
            content = json.dumps(_default_data(), indent=2, ensure_ascii=False)

        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(content)


# ── YAML parser ──────────────────────────────────────────────────────────────


def _parse_yaml(content: str) -> dict:
    """Parse YAML config. Uses PyYAML if available, else a minimal fallback."""
    try:
        import yaml  # type: ignore
        return yaml.safe_load(content) or {}
    except ImportError:
        pass
    return _parse_yaml_fallback(content)


def _parse_yaml_fallback(content: str) -> dict:
    """Minimal YAML parser for the exact subset used by our config.

    Handles:
      - Block mappings with consistent indentation
      - Inline lists:  [22, 30]
      - Inline dicts:  {healthy: [22, 30], warning: [18, 35]}
      - Quoted keys/values
      - Inline comments (#)
    """
    # Collect non-empty, non-pure-comment lines with their indent
    lines = []
    for raw in content.splitlines():
        stripped_r = raw.rstrip()
        stripped = stripped_r.lstrip()
        if not stripped or stripped.startswith('#'):
            continue
        indent = len(stripped_r) - len(stripped)
        lines.append((indent, stripped))

    result, _ = _parse_block(lines, 0, 0)
    return result or {}


def _parse_block(lines: list, start: int, min_indent: int) -> tuple:
    """Parse a block mapping. Returns (dict, next_idx)."""
    result = {}
    i = start

    while i < len(lines):
        indent, line = lines[i]

        if indent < min_indent:
            break

        # Skip unexpected over-indented lines (shouldn't happen in valid config)
        if indent > min_indent and min_indent > 0:
            i += 1
            continue

        if ':' not in line:
            i += 1
            continue

        # Split on the first colon that is not inside brackets
        key_raw, rest = _split_key_value(line)
        key = key_raw.strip().strip('"\'')
        rest = _strip_inline_comment(rest.strip())

        if rest:
            result[key] = _parse_inline_value(rest)
            i += 1
        else:
            # Block value follows (more indented)
            i += 1
            if i < len(lines) and lines[i][0] > min_indent:
                sub_indent = lines[i][0]
                sub_result, i = _parse_block(lines, i, sub_indent)
                result[key] = sub_result
            else:
                result[key] = None

    return result, i


def _split_key_value(line: str) -> tuple:
    """Split 'key: value' on the first top-level colon."""
    depth = 0
    for idx, ch in enumerate(line):
        if ch in '[{':
            depth += 1
        elif ch in ']}':
            depth -= 1
        elif ch == ':' and depth == 0:
            return line[:idx], line[idx + 1:]
    return line, ''


def _strip_inline_comment(s: str) -> str:
    """Remove trailing `# comment` from a value string."""
    depth = 0
    for i, ch in enumerate(s):
        if ch in '[{':
            depth += 1
        elif ch in ']}':
            depth -= 1
        elif ch == '#' and depth == 0 and (i == 0 or s[i - 1] in ' \t'):
            return s[:i].rstrip()
    return s


def _parse_inline_value(s: str):
    """Parse an inline YAML value: scalar, list, or dict."""
    s = s.strip()
    if s.startswith('['):
        return _parse_inline_list(s)
    if s.startswith('{'):
        return _parse_inline_dict(s)
    return _parse_scalar(s)


def _parse_inline_list(s: str) -> list:
    """Parse `[num, num, ...]` → list of numbers/strings."""
    inner = s.strip()
    if inner.startswith('[') and inner.endswith(']'):
        inner = inner[1:-1]
    else:
        inner = inner.lstrip('[')
    return [_parse_scalar(x.strip()) for x in inner.split(',') if x.strip()]


def _parse_inline_dict(s: str) -> dict:
    """Parse `{key: val, key: val}` → dict."""
    inner = s.strip()
    if inner.startswith('{') and inner.endswith('}'):
        inner = inner[1:-1].strip()
    if not inner:
        return {}
    result = {}
    for item in _split_at_commas(inner):
        item = item.strip()
        if ':' not in item:
            continue
        k, rest = _split_key_value(item)
        result[k.strip().strip('"\'').strip()] = _parse_inline_value(rest.strip())
    return result


def _split_at_commas(s: str) -> list:
    """Split on commas not inside brackets."""
    items = []
    depth = 0
    current: list = []
    for ch in s:
        if ch in '[{':
            depth += 1
        elif ch in ']}':
            depth -= 1
        if ch == ',' and depth == 0:
            items.append(''.join(current))
            current = []
        else:
            current.append(ch)
    if current:
        items.append(''.join(current))
    return items


def _parse_scalar(s: str):
    """Parse a scalar value: int, float, or string.

    Quoted values (with single or double quotes) are always returned as strings.
    """
    s = s.strip()
    # Quoted strings stay as strings — no numeric conversion
    if (s.startswith('"') and s.endswith('"')) or \
       (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    if not s:
        return s
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


# ── Helpers ──────────────────────────────────────────────────────────────────


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep-merge *override* into *base*, returning a new dict.

    Dict values are merged recursively; all other types replace the base.
    """
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _default_data() -> dict:
    """Return the default configuration as a plain Python dict."""
    return {
        'version': '1.0',
        'preflop': {
            'vpip':         {'healthy': [22, 30], 'warning': [18, 35]},
            'pfr':          {'healthy': [17, 25], 'warning': [14, 28]},
            'three_bet':    {'healthy': [7, 12],  'warning': [4, 15]},
            'fold_to_3bet': {'healthy': [40, 55], 'warning': [30, 65]},
            'ats':          {'healthy': [30, 45], 'warning': [20, 55]},
        },
        'postflop': {
            'af':           {'healthy': [2.0, 3.5], 'warning': [1.5, 4.5]},
            'wtsd':         {'healthy': [25, 33],   'warning': [20, 38]},
            'wsd':          {'healthy': [48, 55],   'warning': [42, 60]},
            'cbet':         {'healthy': [60, 75],   'warning': [50, 85]},
            'fold_to_cbet': {'healthy': [35, 50],   'warning': [25, 60]},
            'check_raise':  {'healthy': [6, 12],    'warning': [3, 18]},
        },
        'positions': {
            'vpip': {
                'UTG':   {'healthy': [12, 18], 'warning': [9, 24]},
                'UTG+1': {'healthy': [13, 20], 'warning': [10, 26]},
                'MP':    {'healthy': [15, 22], 'warning': [11, 28]},
                'MP+1':  {'healthy': [16, 23], 'warning': [12, 29]},
                'HJ':    {'healthy': [17, 24], 'warning': [13, 31]},
                'CO':    {'healthy': [22, 30], 'warning': [17, 37]},
                'BTN':   {'healthy': [30, 45], 'warning': [24, 55]},
                'SB':    {'healthy': [20, 32], 'warning': [15, 40]},
                'BB':    {'healthy': [25, 42], 'warning': [19, 52]},
            },
            'pfr': {
                'UTG':   {'healthy': [10, 16], 'warning': [7, 20]},
                'UTG+1': {'healthy': [11, 17], 'warning': [8, 21]},
                'MP':    {'healthy': [12, 19], 'warning': [9, 24]},
                'MP+1':  {'healthy': [13, 20], 'warning': [10, 25]},
                'HJ':    {'healthy': [14, 21], 'warning': [11, 26]},
                'CO':    {'healthy': [18, 27], 'warning': [13, 33]},
                'BTN':   {'healthy': [25, 40], 'warning': [19, 50]},
                'SB':    {'healthy': [15, 25], 'warning': [10, 32]},
                'BB':    {'healthy': [8, 15],  'warning': [5, 20]},
            },
        },
    }


def _default_yaml_template() -> str:
    """Return the default config as a human-readable YAML string."""
    return """\
# Poker Stats Targets Configuration
# Generated by: python main.py config --init
#
# Each stat has two ranges:
#   healthy: ideal range  (green badge)
#   warning: caution range (yellow badge) — outside this is danger (red badge)
#
# To customise: change only the values you want; the rest use these defaults.
# Validate your changes with: python main.py config --validate

version: "1.0"

# ── Preflop Stats (6-max NL cash games) ───────────────────────────────────
preflop:
  vpip:
    healthy: [22, 30]    # Voluntary Put $ In Pot % (ideal: 22-30%)
    warning: [18, 35]
  pfr:
    healthy: [17, 25]    # Preflop Raise % (ideal: 17-25%)
    warning: [14, 28]
  three_bet:
    healthy: [7, 12]     # 3-Bet % (ideal: 7-12%)
    warning: [4, 15]
  fold_to_3bet:
    healthy: [40, 55]    # Fold to 3-Bet % (ideal: 40-55%)
    warning: [30, 65]
  ats:
    healthy: [30, 45]    # Attempt to Steal % (ideal: 30-45%)
    warning: [20, 55]

# ── Postflop Stats ─────────────────────────────────────────────────────────
postflop:
  af:
    healthy: [2.0, 3.5]  # Aggression Factor (ideal: 2.0-3.5)
    warning: [1.5, 4.5]
  wtsd:
    healthy: [25, 33]    # Went To Showdown % (ideal: 25-33%)
    warning: [20, 38]
  wsd:
    healthy: [48, 55]    # Won $ at Showdown % (ideal: 48-55%)
    warning: [42, 60]
  cbet:
    healthy: [60, 75]    # Continuation Bet % (ideal: 60-75%)
    warning: [50, 85]
  fold_to_cbet:
    healthy: [35, 50]    # Fold to CBet % (ideal: 35-50%)
    warning: [25, 60]
  check_raise:
    healthy: [6, 12]     # Check-Raise % (ideal: 6-12%)
    warning: [3, 18]

# ── Per-Position Targets (VPIP and PFR) ───────────────────────────────────
positions:
  vpip:
    UTG:   {healthy: [12, 18], warning: [9, 24]}
    UTG+1: {healthy: [13, 20], warning: [10, 26]}
    MP:    {healthy: [15, 22], warning: [11, 28]}
    MP+1:  {healthy: [16, 23], warning: [12, 29]}
    HJ:    {healthy: [17, 24], warning: [13, 31]}
    CO:    {healthy: [22, 30], warning: [17, 37]}
    BTN:   {healthy: [30, 45], warning: [24, 55]}
    SB:    {healthy: [20, 32], warning: [15, 40]}
    BB:    {healthy: [25, 42], warning: [19, 52]}
  pfr:
    UTG:   {healthy: [10, 16], warning: [7, 20]}
    UTG+1: {healthy: [11, 17], warning: [8, 21]}
    MP:    {healthy: [12, 19], warning: [9, 24]}
    MP+1:  {healthy: [13, 20], warning: [10, 25]}
    HJ:    {healthy: [14, 21], warning: [11, 26]}
    CO:    {healthy: [18, 27], warning: [13, 33]}
    BTN:   {healthy: [25, 40], warning: [19, 50]}
    SB:    {healthy: [15, 25], warning: [10, 32]}
    BB:    {healthy: [8, 15],  warning: [5, 20]}
"""
