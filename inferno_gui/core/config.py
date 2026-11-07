"""Inferno Configuration Management.

Handles reading/writing inferno ALSA config (~/.asoundrc) and statime TOML configs.
"""

import os
import re
from pathlib import Path
from typing import Optional, Dict, Any
import tomli
import tomli_w


class InfernoConfigError(Exception):
    """Configuration error."""
    pass


class InfernoConfig:
    """Manages inferno ALSA plugin configuration (.asoundrc)."""
    
    DEFAULT_CONFIG = {
        'name': 'Inferno',
        'sample_rate': 48000,
        'tx_channels': 24,
        'rx_channels': 24,
        'bind_ip': '',
        'device_name': 'Inferno',
    }
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or os.path.expanduser("~/.asoundrc")
        self._data = self.DEFAULT_CONFIG.copy()
        self._loaded = False
    
    def load(self) -> bool:
        """Load configuration from .asoundrc. Returns True if loaded, False if not found."""
        if not os.path.exists(self.config_path):
            return False
        
        try:
            with open(self.config_path, 'r') as f:
                content = f.read()
            
            # Parse the inferno pcm block
            self._parse_asoundrc(content)
            self._loaded = True
            return True
        except Exception as e:
            raise InfernoConfigError(f"Failed to parse {self.config_path}: {e}")
    
    def _parse_asoundrc(self, content: str):
        """Parse inferno pcm block from .asoundrc."""
        # Find pcm.inferno block
        pcm_match = re.search(r'pcm\.inferno\s*\{([^}]+)\}', content, re.DOTALL)
        if not pcm_match:
            return
        
        block = pcm_match.group(1)
        
        # Extract key-value pairs
        patterns = {
            'name': r'NAME\s+"([^"]+)"',
            'sample_rate': r'SAMPLE_RATE\s+"([^"]+)"',
            'tx_channels': r'TX_CHANNELS\s+(\d+)',
            'rx_channels': r'RX_CHANNELS\s+(\d+)',
            'bind_ip': r'BIND_IP\s+"([^"]+)"',
        }
        
        for key, pattern in patterns.items():
            match = re.search(pattern, block)
            if match:
                value = match.group(1)
                if key in ('sample_rate', 'tx_channels', 'rx_channels'):
                    self._data[key] = int(value)
                else:
                    self._data[key] = value
    
    def save(self, backup: bool = True):
        """Save configuration to .asoundrc."""
        if backup and os.path.exists(self.config_path):
            backup_path = self.config_path + '.bak'
            os.rename(self.config_path, backup_path)
        
        content = self._generate_asoundrc()
        with open(self.config_path, 'w') as f:
            f.write(content)
        self._loaded = True
    
    def _generate_asoundrc(self) -> str:
        """Generate .asoundrc content."""
        return f'''pcm.inferno {{
    type inferno

    NAME "{self._data['name']}"
    SAMPLE_RATE "{self._data['sample_rate']}"

    TX_CHANNELS {self._data['tx_channels']}
    RX_CHANNELS {self._data['rx_channels']}

    BIND_IP "{self._data['bind_ip']}"

    hint {{
        show on
        description "Inferno Dante Virtual Soundcard"
    }}
}}

'''
    
    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)
    
    def set(self, key: str, value: Any):
        if key in self._data:
            self._data[key] = value
    
    @property
    def name(self) -> str:
        return self._data['name']
    
    @property
    def sample_rate(self) -> int:
        return self._data['sample_rate']
    
    @property
    def tx_channels(self) -> int:
        return self._data['tx_channels']
    
    @property
    def rx_channels(self) -> int:
        return self._data['rx_channels']
    
    @property
    def bind_ip(self) -> str:
        return self._data['bind_ip']
    
    @property
    def device_name(self) -> str:
        return self._data.get('device_name', 'Inferno')
    
    def to_dict(self) -> Dict[str, Any]:
        return self._data.copy()


class StatimeConfig:
    """Manages statime TOML configuration files."""
    
    def __init__(self, config_path: str):
        self.config_path = config_path
        self._data: Dict[str, Any] = {}
        self._loaded = False
    
    def load(self) -> bool:
        """Load configuration from TOML file."""
        if not os.path.exists(self.config_path):
            return False
        
        try:
            with open(self.config_path, 'rb') as f:
                self._data = tomli.load(f)
            self._loaded = True
            return True
        except Exception as e:
            raise InfernoConfigError(f"Failed to parse {self.config_path}: {e}")
    
    def save(self):
        """Save configuration to TOML file."""
        with open(self.config_path, 'wb') as f:
            tomli_w.dump(self._data, f)
        self._loaded = True
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get value using dot notation (e.g., 'global.interface')."""
        parts = key.split('.')
        data = self._data
        for part in parts:
            if isinstance(data, dict) and part in data:
                data = data[part]
            else:
                return default
        return data
    
    def set(self, key: str, value: Any):
        """Set value using dot notation."""
        parts = key.split('.')
        data = self._data
        for part in parts[:-1]:
            if part not in data:
                data[part] = {}
            data = data[part]
        data[parts[-1]] = value
    
    def set_interface(self, interface: str):
        """Set the network interface in the config."""
        # Try common locations
        for key in ('global.interface', 'interface', 'port.interface'):
            if self.get(key) is not None:
                self.set(key, interface)
                return
        # Default to global.interface
        self.set('global.interface', interface)
    
    def get_interface(self) -> Optional[str]:
        """Get the configured network interface."""
        for key in ('global.interface', 'interface', 'port.interface'):
            val = self.get(key)
            if val:
                return val
        return None


def get_available_interfaces() -> list:
    """Get list of available network interfaces (excluding loopback)."""
    import subprocess
    try:
        result = subprocess.run(['ip', 'link', 'show'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            interfaces = re.findall(r'^\d+: (\w+):', result.stdout, re.MULTILINE)
            return [iface for iface in interfaces if iface != 'lo']
    except Exception:
        pass
    return []


def get_interface_ip(interface: str) -> Optional[str]:
    """Get IP address for an interface."""
    import subprocess
    try:
        result = subprocess.run(['ip', '-br', 'addr', 'show', interface], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            parts = result.stdout.strip().split()
            if len(parts) >= 3:
                ip_cidr = parts[2]
                return ip_cidr.split('/')[0]
    except Exception:
        pass
    return None


def get_work_dir() -> Path:
    """Get the inferno working directory."""
    return Path.home() / 'audio-inferno'


def get_statime_dir() -> Path:
    return get_work_dir() / 'statime'


def get_inferno_dir() -> Path:
    return get_work_dir() / 'inferno'


def get_default_statime_config(ptp_version: str = 'v2') -> Path:
    """Get default statime config path for PTP version."""
    statime_dir = get_statime_dir()
    if ptp_version == 'v1':
        return statime_dir / 'inferno-ptpv1.toml'
    return statime_dir / 'inferno-ptpv2.toml'


def get_statime_binary() -> Path:
    return get_statime_dir() / 'target' / 'debug' / 'statime'


def get_inferno_plugin() -> Path:
    return get_inferno_dir() / 'target' / 'debug' / 'libasound_module_pcm_inferno.so'