"""Statime Log Parser – filters and summarizes statime output.

Reduces verbose statime logs to one line per second with key metrics,
similar to ptp4l output format.
"""

import re
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from enum import Enum


class LogSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class ParsedLogEntry:
    severity: LogSeverity
    timestamp: str
    message: str
    raw: str
    # Key metrics
    offset_ns: Optional[int] = None
    freq_ppb: Optional[int] = None
    state: Optional[str] = None
    path_delay_ns: Optional[int] = None


# Patterns for extracting key metrics from the statime log format
STATIME_PATTERNS = [
    # "Estimated offset -123.45ns+-12.3ns, freq 1.234+-0.567, delay 4567.8+-12.3"
    {
        'key': 'offset',
        'pattern': re.compile(r'Estimated offset (-?[\d.]+)ns\+-'),
    },
    {
        'key': 'freq_ppb',
        'pattern': re.compile(r'freq (-?[\d.]+)\+-'),
    },
    {
        'key': 'path_delay',
        'pattern': re.compile(r'delay (-?[\d.]+)\+-'),
    },
    # Real statime state transitions, e.g. "new state for port 0: Listening -> Slave"
    {
        'key': 'state',
        'pattern': re.compile(r'new state for port \d+: \w+ -> (\w+)'),
    },
]


class StatimeLogParser:
    """Parses and filters statime log output."""
    
    def __init__(self, filter_interval: float = 1.0):
        self.filter_interval = filter_interval  # seconds between summary lines
        self._last_summary_time = 0.0  # first line is shown immediately
        self._pending_metrics: Dict[str, any] = {}
        self._last_state: Optional[str] = None
        self._counters = {
            'errors': 0,
            'warnings': 0,
            'state_changes': 0,
        }
        self._last_entry: Optional[ParsedLogEntry] = None
    
    def parse_line(self, line: str) -> Optional[ParsedLogEntry]:
        """Parse a single log line. Returns ParsedLogEntry if significant, None otherwise."""
        line = line.rstrip('\n\r')
        if not line.strip():
            return None
        
        # Extract timestamp if present
        timestamp = self._extract_timestamp(line)
        
        # Severity comes from the log level prefix, not from message text
        # (e.g. a "ParseError" in a TRACE line is still INFO)
        level_match = re.match(r'^\S+\s+(TRACE|DEBUG|INFO|WARN|ERROR)\s', line)
        if level_match:
            level = level_match.group(1)
            if level == 'ERROR':
                severity = LogSeverity.ERROR
            elif level == 'WARN':
                severity = LogSeverity.WARNING
            else:
                severity = LogSeverity.INFO
            if severity == LogSeverity.ERROR:
                self._counters['errors'] += 1
            elif severity == LogSeverity.WARNING:
                self._counters['warnings'] += 1
        else:
            severity = LogSeverity.INFO
        
        # Check all patterns
        entry = ParsedLogEntry(
            severity=severity,
            timestamp=timestamp,
            message=line[:200],  # Truncate for display
            raw=line,
        )
        
        for pat_info in STATIME_PATTERNS:
            match = pat_info['pattern'].search(line)
            if match:
                # Update metrics
                if pat_info['key'] == 'offset':
                    try:
                        entry.offset_ns = round(float(match.group(1)))
                    except (ValueError, IndexError):
                        pass
                elif pat_info['key'] == 'freq_ppb':
                    try:
                        entry.freq_ppb = round(float(match.group(1)) * 1000)
                    except (ValueError, IndexError):
                        pass
                elif pat_info['key'] == 'path_delay':
                    try:
                        entry.path_delay_ns = round(float(match.group(1)))
                    except (ValueError, IndexError):
                        pass
                elif pat_info['key'] == 'state':
                    entry.state = match.group(1).upper()
                    self._counters['state_changes'] += 1
        
        self._last_entry = entry
        
        # Always update pending metrics for ANY line that has metrics (even if filtered from display)
        self.update_pending_metrics(entry)
        
        # Always return entry for important events (errors, warnings, explicit state changes)
        # But NOT for TRACE lines with estimated offset/freq - those only update metrics
        has_explicit_state = entry.state is not None
        has_error_warning = entry.severity != LogSeverity.INFO
        
        is_important = has_explicit_state or has_error_warning
        
        if is_important:
            return entry
        
        # For regular info lines, only return if enough time has passed
        # (filtering to ~1 line per second)
        current_time = time.monotonic()
        if current_time - self._last_summary_time >= self.filter_interval:
            self._last_summary_time = current_time
            # Create a summary entry with current metrics
            return self._create_summary_entry(entry)
        
        return None
    
    def _create_summary_entry(self, base_entry: ParsedLogEntry) -> ParsedLogEntry:
        """Create a summary line with key metrics."""
        parts = []
        
        if self._last_state:
            parts.append(f"state={self._last_state}")
        
        if base_entry.offset_ns is not None:
            parts.append(f"offset={base_entry.offset_ns}ns")
        elif self._pending_metrics.get('offset_ns') is not None:
            parts.append(f"offset={self._pending_metrics['offset_ns']}ns")
        
        if base_entry.freq_ppb is not None:
            parts.append(f"freq={base_entry.freq_ppb}ppb")
        elif self._pending_metrics.get('freq_ppb') is not None:
            parts.append(f"freq={self._pending_metrics['freq_ppb']}ppb")
        
        if base_entry.path_delay_ns is not None:
            parts.append(f"path_delay={base_entry.path_delay_ns}ns")
        elif self._pending_metrics.get('path_delay_ns') is not None:
            parts.append(f"path_delay={self._pending_metrics['path_delay_ns']}ns")
        
        if not parts:
            parts.append("running")
        
        message = " | ".join(parts)
        
        return ParsedLogEntry(
            severity=LogSeverity.INFO,
            timestamp=base_entry.timestamp,
            message=message,
            raw=base_entry.raw,
            offset_ns=base_entry.offset_ns if base_entry.offset_ns is not None else self._pending_metrics.get('offset_ns'),
            freq_ppb=base_entry.freq_ppb if base_entry.freq_ppb is not None else self._pending_metrics.get('freq_ppb'),
            state=self._last_state,
            path_delay_ns=base_entry.path_delay_ns if base_entry.path_delay_ns is not None else self._pending_metrics.get('path_delay_ns'),
        )
    
    def _extract_timestamp(self, line: str) -> str:
        """Extract timestamp from log line."""
        # Common timestamp formats
        patterns = [
            r'\[(\d{2}:\d{2}:\d{2}\.\d+)\]',  # [HH:MM:SS.mmm]
            r'(\d{2}:\d{2}:\d{2}\.\d+)',      # HH:MM:SS.mmm
            r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})',  # ISO format
        ]
        for pat in patterns:
            match = re.search(pat, line)
            if match:
                return match.group(1)
        return time.strftime("%H:%M:%S")
    
    def update_pending_metrics(self, entry: ParsedLogEntry):
        """Update pending metrics for summary generation."""
        if entry.offset_ns is not None:
            self._pending_metrics['offset_ns'] = entry.offset_ns
        if entry.freq_ppb is not None:
            self._pending_metrics['freq_ppb'] = entry.freq_ppb
        if entry.path_delay_ns is not None:
            self._pending_metrics['path_delay_ns'] = entry.path_delay_ns
        if entry.state is not None:
            # Metrics measured before a state transition are stale - but a
            # repeated same-state line ("Slave -> Slave") is not a real
            # transition, so the pending metrics stay valid in that case.
            if entry.state != self._last_state:
                for key in ('offset_ns', 'freq_ppb', 'path_delay_ns'):
                    self._pending_metrics.pop(key, None)
            self._last_state = entry.state
    
    def get_sync_status(self) -> Dict[str, any]:
        """Get current sync status for UI indicators."""
        status = {
            'state': self._last_state or 'UNKNOWN',
            'offset_ns': self._pending_metrics.get('offset_ns'),
            'freq_ppb': self._pending_metrics.get('freq_ppb'),
            'path_delay_ns': self._pending_metrics.get('path_delay_ns'),
            'errors': self._counters['errors'],
            'warnings': self._counters['warnings'],
        }
        return status
    
    def get_aggregate_severity(self) -> LogSeverity:
        """Get aggregate severity for health indicator."""
        if self._counters['errors'] > 0:
            return LogSeverity.ERROR
        if self._counters['warnings'] > 0:
            return LogSeverity.WARNING
        return LogSeverity.INFO
    
    def reset_counters(self):
        self._counters = {'errors': 0, 'warnings': 0, 'state_changes': 0}
    
    def reset_all(self):
        self.reset_counters()
        self._last_summary_time = 0.0
        self._pending_metrics = {}
        self._last_state = None
        self._last_entry = None


def format_log_entry(entry: ParsedLogEntry) -> str:
    """Format a parsed log entry for display."""
    ts = f"[{entry.timestamp}] " if entry.timestamp else ""
    return f"{ts}{entry.message}"