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


# Patterns for extracting key metrics from statime output
STATIME_PATTERNS = [
    # Offset/frequency patterns (common in PTP logs)
    {
        'key': 'offset',
        'pattern': re.compile(r'offset\s*[=:]\s*(-?\d+\.?\d*)\s*ns?'),
        'severity': LogSeverity.INFO,
    },
    {
        'key': 'offset',
        'pattern': re.compile(r'Estimated\s+offset\s+(-?\d+\.?\d*)\s*ns'),
        'severity': LogSeverity.INFO,
    },
    {
        'key': 'rms_offset',
        'pattern': re.compile(r'rms\s+(-?\d+)'),
        'severity': LogSeverity.INFO,
    },
    {
        'key': 'freq_ppb',
        'pattern': re.compile(r'freq\s*[=:]\s*(-?\d+\.?\d*)\s*ppb?'),
        'severity': LogSeverity.INFO,
    },
    {
        'key': 'freq_ppb',
        'pattern': re.compile(r'freq\s+(-?\d+\.?\d*)'),
        'severity': LogSeverity.INFO,
    },
    {
        'key': 'path_delay',
        'pattern': re.compile(r'path_delay\s+(\d+)'),
        'severity': LogSeverity.INFO,
    },
    {
        'key': 'delay',
        'pattern': re.compile(r'delay\s+(\d+\.?\d*)'),
        'severity': LogSeverity.INFO,
    },
    # State transitions
    {
        'key': 'state_master',
        'pattern': re.compile(r'(?:to|entered)\s+MASTER', re.IGNORECASE),
        'severity': LogSeverity.INFO,
        'state': 'MASTER',
    },
    {
        'key': 'state_slave',
        'pattern': re.compile(r'(?:to|entered)\s+SLAVE', re.IGNORECASE),
        'severity': LogSeverity.INFO,
        'state': 'SLAVE',
    },
    {
        'key': 'state_passive',
        'pattern': re.compile(r'(?:to|entered)\s+PASSIVE', re.IGNORECASE),
        'severity': LogSeverity.INFO,
        'state': 'PASSIVE',
    },
    {
        'key': 'state_listening',
        'pattern': re.compile(r'(?:to|entered)\s+LISTENING', re.IGNORECASE),
        'severity': LogSeverity.INFO,
        'state': 'LISTENING',
    },
    {
        'key': 'state_uncalibrated',
        'pattern': re.compile(r'(?:to|entered)\s+UNCALIBRATED', re.IGNORECASE),
        'severity': LogSeverity.WARNING,
        'state': 'UNCALIBRATED',
    },
    {
        'key': 'state_faulty',
        'pattern': re.compile(r'(?:to|entered)\s+FAULTY', re.IGNORECASE),
        'severity': LogSeverity.ERROR,
        'state': 'FAULTY',
    },
    # Errors and warnings
    {
        'key': 'error',
        'pattern': re.compile(r'(?i)error[:\s]'),
        'severity': LogSeverity.ERROR,
    },
    {
        'key': 'warning',
        'pattern': re.compile(r'(?i)warn(?:ing)?[:\s]'),
        'severity': LogSeverity.WARNING,
    },
    {
        'key': 'sync_lost',
        'pattern': re.compile(r'(?i)sync\s+lost|lost\s+sync'),
        'severity': LogSeverity.ERROR,
    },
    {
        'key': 'timeout',
        'pattern': re.compile(r'(?i)timeout'),
        'severity': LogSeverity.WARNING,
    },
    {
        'key': 'port_state',
        'pattern': re.compile(r'port\s+\d+:\s+(\w+)'),
        'severity': LogSeverity.INFO,
    },
]


class StatimeLogParser:
    """Parses and filters statime log output."""
    
    def __init__(self, filter_interval: float = 1.0):
        self.filter_interval = filter_interval  # seconds between summary lines
        self._last_summary_time = 0.0
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
        
        # Check all patterns
        entry = ParsedLogEntry(
            severity=LogSeverity.INFO,
            timestamp=timestamp,
            message=line[:200],  # Truncate for display
            raw=line,
        )
        
        matched_patterns = []
        for pat_info in STATIME_PATTERNS:
            match = pat_info['pattern'].search(line)
            if match:
                matched_patterns.append((pat_info, match))
                
                # Update metrics
                if pat_info['key'] in ('offset', 'rms_offset'):
                    try:
                        entry.offset_ns = abs(int(float(match.group(1))))
                    except (ValueError, IndexError):
                        pass
                elif pat_info['key'] == 'freq_ppb':
                    try:
                        entry.freq_ppb = int(float(match.group(1)))
                    except (ValueError, IndexError):
                        pass
                elif pat_info['key'] in ('path_delay', 'delay'):
                    try:
                        entry.path_delay_ns = int(float(match.group(1)))
                    except (ValueError, IndexError):
                        pass
                elif 'state' in pat_info:
                    entry.state = pat_info['state']
                
                # Track severity
                if pat_info['severity'] == LogSeverity.ERROR:
                    self._counters['errors'] += 1
                elif pat_info['severity'] == LogSeverity.WARNING:
                    self._counters['warnings'] += 1
                if 'state' in pat_info:
                    self._counters['state_changes'] += 1
        
        # Determine overall severity
        if any(p[0]['severity'] == LogSeverity.ERROR for p in matched_patterns):
            entry.severity = LogSeverity.ERROR
        elif any(p[0]['severity'] == LogSeverity.WARNING for p in matched_patterns):
            entry.severity = LogSeverity.WARNING
        
        self._last_entry = entry
        
        # Always return entry for important events (errors, warnings, state changes)
        is_important = (
            entry.severity != LogSeverity.INFO or
            entry.state is not None or
            entry.offset_ns is not None
        )
        
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
        
        if not parts:
            parts.append("running")
        
        message = " | ".join(parts)
        
        return ParsedLogEntry(
            severity=LogSeverity.INFO,
            timestamp=base_entry.timestamp,
            message=message,
            raw=base_entry.raw,
            offset_ns=base_entry.offset_ns or self._pending_metrics.get('offset_ns'),
            freq_ppb=base_entry.freq_ppb or self._pending_metrics.get('freq_ppb'),
            state=self._last_state,
            path_delay_ns=base_entry.path_delay_ns or self._pending_metrics.get('path_delay_ns'),
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
            self._last_state = entry.state
            self._pending_metrics['state'] = entry.state
        # Infer state from metrics if no explicit state transition
        elif entry.offset_ns is not None or entry.freq_ppb is not None:
            # If we're getting offset/freq data, we're likely in SLAVE state (synchronized)
            if self._last_state != 'SLAVE':
                self._last_state = 'SLAVE'
                self._pending_metrics['state'] = 'SLAVE'
    
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