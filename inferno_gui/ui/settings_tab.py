"""Settings Tab – Configure Inferno audio parameters and system settings."""

from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton,
    QGroupBox, QFormLayout, QComboBox, QSpinBox, QLineEdit,
    QCheckBox, QScrollArea, QMessageBox, QGridLayout, QStyle,
    QRadioButton, QButtonGroup, QDoubleSpinBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import QFont, QIcon

from inferno_gui.core.app_settings import user_settings
from inferno_gui.core.config import (
    InfernoConfig,
    StatimeConfig,
    get_actual_user_home,
    get_available_interfaces,
    get_interface_ip,
    get_default_statime_config,
    get_work_dir,
    sync_bind_ip,
)
from inferno_gui.core.log_parser import LogSeverity
from inferno_gui.core.ownership import chown_qsettings
from inferno_gui.core.pipewire_latency import read_pipewire_latency
from inferno_gui.ui.latency_overview import LatencyBar
from inferno_gui.ui.url_utils import open_url_as_user


def _asset_icon(name: str) -> QIcon:
    """Load a bundled asset icon; null QIcon when the asset is missing."""
    return QIcon(str(Path(__file__).resolve().parent.parent / 'assets' / name))


def _set_port_interval(port: dict, key: str, value) -> None:
    """Update an interval value in a statime port table, in place.

    The installer templates name these keys with underscores
    (sync_interval) while statime's canonical form is hyphenated
    (sync-interval): update whichever key the file already defines —
    keeping its key style — and only create the hyphenated name when
    the table has neither.
    """
    for existing in (key, key.replace('-', '_')):
        if existing in port:
            port[existing] = value
            return
    port[key] = value


_LATENCY_MS_TO_NS = 1_000_000


def _ms_to_ns(ms: float) -> int:
    """Milliseconds (spinbox display) → integer nanoseconds (storage)."""
    return int(round(ms * _LATENCY_MS_TO_NS))


def _ns_to_ms(ns: int) -> float:
    """Integer nanoseconds (storage) → milliseconds, rounded to the
    0.1 ms display grid the spinboxes use."""
    return round(ns / _LATENCY_MS_TO_NS, 1)


# Verbatim honesty note for the Latency Overview (user-approved
# wording): inferno's RX/TX latency handling has an upstream
# asymmetry the overview must not paper over.
_LATENCY_HONESTY_NOTE = (
    "Inferno currently advertises RX and applies TX on receive — "
    "upstream FIXME; values shown are the configured ones."
)

# Width cap for the two-column scroll content (user report: on a
# wide/maximized window every group stretched to ~937px and the sparse
# right column looked absurdly wide).  980 with the 1:1 column stretch
# and the right column's 340px cap gives left ≈ 618px, right ≈ 340px —
# both columns in their approved bands.  Small windows never notice:
# the construction sizeHint (~570px) sits far below the cap, so the
# compact 770px layout is unchanged.
_CONTENT_MAX_WIDTH = 980

# Live-refresh cadence for the Latency Overview while the settings
# tab is VISIBLE (user expectation: the estimate must track quantum
# changes made while the tab is open — e.g. an app forcing the
# quantum — not only repaint on every tab re-entry).
_LATENCY_REFRESH_MS = 5000


class SettingsTab(QWidget):
    """Settings tab for configuring Inferno and statime."""
    
    # Signals
    settings_changed = pyqtSignal()
    interface_changed = pyqtSignal(str)
    ptp_version_changed = pyqtSignal(str)
    dirty_changed = pyqtSignal(bool)  # True when unsaved changes exist
    
    def __init__(self, control_tab=None):
        super().__init__()
        self.control_tab = control_tab
        self.inferno_config = InfernoConfig()
        self._dirty = False
        self._original_values = {}
        # True while the interface selection is restored programmatically
        # (startup load, refresh, control-tab push); a genuine user
        # selection change additionally syncs BIND_IP (see
        # _on_iface_changed), restores must not.
        self._restoring_iface = False
        # The single live-refresh timer for the Latency Overview,
        # created lazily by the first showEvent (see _ensure_latency_timer).
        self._latency_timer = None
        self._init_ui()
        self.load_settings()
        # NOTE: the Latency Overview is NOT refreshed here — querying
        # pw-metadata at construction would block for up to 2 s before
        # the tab is ever shown (and shells out in unrelated widget
        # tests). showEvent refreshes it on first display and on every
        # tab activation.
        self._capture_original_values()
        self._setup_dirty_tracking()
    
    def _init_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        # Capped content centers in wide viewports instead of hugging
        # the left edge.  Vertical behavior is unchanged: AlignTop
        # keeps the content anchored where the trailing stretch row
        # already held it, and the fallback scroll bar still appears
        # for windows shorter than the content.
        scroll.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        content = QWidget()
        # Cap the content so wide/maximized windows do not stretch
        # every group to the viewport (see _CONTENT_MAX_WIDTH).
        content.setMaximumWidth(_CONTENT_MAX_WIDTH)
        # Two-column arrangement (user-approved layout contract):
        #   left column  — Network Interface, Audio Parameters,
        #                  Advanced statime Options
        #   right column — Actions, Config Files, with a clean seam at
        #                  the top of the nested stack where the
        #                  "Latency Overview" group of a later task
        #                  will insert
        # The fallback scroll area stays for very small windows; the
        # columns are balanced so no scrolling is needed at standard
        # window heights.
        grid = QGridLayout(content)
        grid.setSpacing(10)
        # 6px outer margins (compact layout, down from 8): the scroll
        # viewport already frames the content; every horizontal pixel
        # counts toward the 770px-viewport budget.
        grid.setContentsMargins(6, 6, 6, 6)

        # ── Network Interface ────────────────────────────────────
        net_group = QGroupBox("Network Interface")
        net_layout = QFormLayout(net_group)
        # 6px spacing (compact layout, down from the 8px default):
        # stacking the PTP radios costs one radio height, and the
        # standard-window (560px) height budget needs it back.
        net_layout.setSpacing(6)
        net_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.iface_combo = QComboBox()
        # Long interface names (bridges, USB/wifi adapters with their
        # IPs) must not dictate the group's width: the combo sizes
        # itself to ~20 characters instead of its longest item. The
        # full text stays readable — the popup list sizes to its items
        # and the combo tooltip carries the current item's text.
        self.iface_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.iface_combo.setMinimumContentsLength(20)
        # 200px usability floor (down from 250): with the PTP radios
        # stacked above, a 250px floor kept the Network group at 401px
        # and the 770px-viewport compact layout out of budget; 200
        # still shows the ~20-character sizing with room to spare.
        self.iface_combo.setMinimumWidth(200)
        self.iface_combo.currentIndexChanged.connect(self._on_iface_changed)
        net_layout.addRow("Dante/PTP Interface:", self.iface_combo)

        self.refresh_iface_btn = QPushButton("↻ Refresh")
        self.refresh_iface_btn.setFixedWidth(100)
        self.refresh_iface_btn.clicked.connect(self._refresh_interfaces)
        net_layout.addRow("", self.refresh_iface_btn)

        self.ip_display = QLabel("—")
        self.ip_display.setStyleSheet("color: #4caf50; font-family: monospace;")
        net_layout.addRow("Current IP:", self.ip_display)

        # PTP Version — the two radios stack VERTICALLY under each
        # other (user-approved compact layout): side by side their
        # 155px hints forced the Network group to a 467px minimum and
        # with it the whole content past the 770px-viewport budget.
        # Stacked, the wider combo row drives the field column alone.
        self.ptp_v1_radio = QRadioButton("PTPv1 (IEEE 1588-2002)")
        self.ptp_v2_radio = QRadioButton("PTPv2 (IEEE 1588-2008)")
        self.ptp_v2_radio.setChecked(True)
        self.ptp_version_group = QButtonGroup(self)
        self.ptp_version_group.addButton(self.ptp_v1_radio, 1)
        self.ptp_version_group.addButton(self.ptp_v2_radio, 2)
        self.ptp_version_group.idToggled.connect(self._on_ptp_version_toggled)
        ptp_ver_layout = QVBoxLayout()
        ptp_ver_layout.setSpacing(2)
        ptp_ver_layout.addWidget(self.ptp_v1_radio)
        ptp_ver_layout.addWidget(self.ptp_v2_radio)
        net_layout.addRow("PTP Version:", ptp_ver_layout)

        # ── Audio Parameters ─────────────────────────────────────
        # QFormLayout with plain rows (user-approved relayout): the two
        # channel rows group first, then the two latency rows —
        # TX Channels → RX Channels → TX Latency → RX Latency — instead
        # of latency interleaving with the channels; the label order
        # keeps each channel/latency pairing readable.
        audio_group = QGroupBox("Audio Parameters")
        audio_layout = QFormLayout(audio_group)
        # 6px spacing and right-aligned labels: the same form-label
        # style as the Network and Advanced groups above and below.
        audio_layout.setSpacing(6)
        audio_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.device_name = QLineEdit("Inferno")
        # 200px floor: keeps the field column readable where the spin
        # rows alone (~95px) would leave it narrow.
        self.device_name.setMinimumWidth(200)
        audio_layout.addRow("Device Name:", self.device_name)

        self.sample_rate = QComboBox()
        for rate in [44100, 48000, 88200, 96000, 176400, 192000]:
            self.sample_rate.addItem(f"{rate} Hz", rate)
        self.sample_rate.setCurrentText("48000 Hz")
        audio_layout.addRow("Sample Rate:", self.sample_rate)

        self.tx_channels = QSpinBox()
        self.tx_channels.setRange(1, 64)
        self.tx_channels.setValue(24)
        self.tx_channels.setSuffix(" channels")
        # Width cap: the spinbox's natural minimum is ~95px at default
        # metrics, so this never binds normally — but with fat widget
        # metrics (font scale, larger style fonts) the hint inflates
        # and Qt clamps the layout minimum to the cap.
        self.tx_channels.setMaximumWidth(140)
        audio_layout.addRow("TX Channels (Output):", self.tx_channels)

        self.rx_channels = QSpinBox()
        self.rx_channels.setRange(1, 64)
        self.rx_channels.setValue(24)
        self.rx_channels.setSuffix(" channels")
        # Same width cap as the TX spinbox.
        self.rx_channels.setMaximumWidth(140)
        audio_layout.addRow("RX Channels (Input):", self.rx_channels)

        # Latency rows follow the channel rows (user-approved relayout):
        # TX Channels → RX Channels → TX Latency → RX Latency — the
        # channels group first, then the latencies.
        self.tx_latency = QDoubleSpinBox()
        self._configure_latency_spin(self.tx_latency)
        audio_layout.addRow("TX Latency:", self.tx_latency)

        self.rx_latency = QDoubleSpinBox()
        self._configure_latency_spin(self.rx_latency)
        audio_layout.addRow("RX Latency:", self.rx_latency)

        # Hint under the latency rows (exact wording per spec), full
        # row width like the rows above it.
        self.latency_hint = QLabel("Takes effect after the next PTP start")
        self.latency_hint.setStyleSheet("color: #aaa; font-size: 11px;")
        audio_layout.addRow(self.latency_hint)

        # Dynamic low-latency warning, visible while either spinbox sits
        # at the 1.0 ms floor (the static tooltip carries the full text).
        # Word wrap: the ~460px one-liner must wrap inside the group
        # instead of imposing its width on the column (the spinbox
        # tooltips keep the full wording at all times).
        self.latency_warning = QLabel(
            "⚠ Below ~1 ms RX underruns become likely — "
            "1.0 ms is the smallest value the GUI offers."
        )
        self.latency_warning.setStyleSheet("color: #ffc107; font-size: 11px;")
        self.latency_warning.setWordWrap(True)
        self.latency_warning.hide()
        audio_layout.addRow(self.latency_warning)

        # The warning only depends on values, never on dirty state —
        # safe to wire up right away (initial state: hidden at 10.0 ms).
        self.tx_latency.valueChanged.connect(self._update_latency_warning)
        self.rx_latency.valueChanged.connect(self._update_latency_warning)
        self._update_latency_warning()

        # ── Advanced statime Options ────────────────────────────
        adv_group = QGroupBox("Advanced statime Options")
        adv_layout = QFormLayout(adv_group)
        # 6px spacing (compact layout, down from the 8px default):
        # same standard-window height reclaim as the Network group.
        adv_layout.setSpacing(6)
        adv_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.ptp_domain = QSpinBox()
        self.ptp_domain.setRange(0, 255)
        self.ptp_domain.setValue(0)
        adv_layout.addRow("PTP Domain:", self.ptp_domain)

        self.sync_interval = QSpinBox()
        self.sync_interval.setRange(-7, 7)
        self.sync_interval.setValue(0)
        self.sync_interval.setSuffix(" (log2 seconds)")
        adv_layout.addRow("Sync Interval:", self.sync_interval)

        self.announce_interval = QSpinBox()
        self.announce_interval.setRange(-7, 7)
        self.announce_interval.setValue(1)
        self.announce_interval.setSuffix(" (log2 seconds)")
        adv_layout.addRow("Announce Interval:", self.announce_interval)

        self.log_level = QComboBox()
        for level in ["ERROR", "WARN", "INFO", "DEBUG", "TRACE"]:
            self.log_level.addItem(level)
        # Log level is locked to TRACE: the log parser and PipeWire node
        # automation only work with trace level (user-approved decision).
        self.log_level.setCurrentText("TRACE")
        self.log_level.setToolTip(
            "The log parser and PipeWire node automation require trace level; "
            "changing it would break status display and node creation."
        )
        self._lock_log_level()
        adv_layout.addRow("Log Level:", self.log_level)

        # ── Config Files ────────────────────────────────────────
        config_group = QGroupBox("Config Files")
        config_layout = QVBoxLayout(config_group)
        config_layout.setSpacing(8)
        # 6px margins (compact layout, down from the 11px style
        # default): the buttons drive the group width, and every saved
        # pixel counts toward the 620px content budget.
        config_layout.setContentsMargins(6, 6, 6, 6)

        # PipeWire override — resolve against the actual user's home
        # (Path.home() is /root when the GUI runs under sudo)
        pw_override_path = get_actual_user_home() / ".config/systemd/user/pipewire.service.d/override.conf"
        self._pw_override_path = pw_override_path
        self.pw_override_btn = QPushButton("Open PipeWire Override")
        try:
            from PyQt6.QtGui import QIcon
            _cfg_icon = QIcon("/usr/share/icons/Papirus/24x24/mimetypes/text-x-generic.svg")
            if not _cfg_icon.isNull():
                self.pw_override_btn.setIcon(_cfg_icon)
                self.pw_override_btn.setIconSize(QSize(16, 16))
        except Exception:
            pass
        self.pw_override_btn.clicked.connect(self._open_pw_override)
        config_layout.addWidget(self.pw_override_btn)
        
        self.pw_override_status = QLabel("Checking...")
        self.pw_override_status.setStyleSheet("color: #aaa; font-size: 11px;")
        # Word wrap: once the status check resolves, this label can
        # hold a long path; wrapped it keeps the (now width-capped)
        # right column at its button-driven minimum instead of
        # imposing the text width on the whole tab.
        self.pw_override_status.setWordWrap(True)
        config_layout.addWidget(self.pw_override_status)
        
        # PTPv1 config
        ptpv1_path = get_default_statime_config('v1')
        self._ptpv1_path = ptpv1_path
        self.ptpv1_btn = QPushButton("Open PTPv1 Config")
        try:
            from PyQt6.QtGui import QIcon
            _cfg_icon = QIcon("/usr/share/icons/Papirus/24x24/mimetypes/text-x-generic.svg")
            if not _cfg_icon.isNull():
                self.ptpv1_btn.setIcon(_cfg_icon)
                self.ptpv1_btn.setIconSize(QSize(16, 16))
        except Exception:
            pass
        self.ptpv1_btn.clicked.connect(self._open_ptpv1_config)
        config_layout.addWidget(self.ptpv1_btn)
        
        # PTPv2 config
        ptpv2_path = get_default_statime_config('v2')
        self._ptpv2_path = ptpv2_path
        self.ptpv2_btn = QPushButton("Open PTPv2 Config")
        try:
            from PyQt6.QtGui import QIcon
            _cfg_icon = QIcon("/usr/share/icons/Papirus/24x24/mimetypes/text-x-generic.svg")
            if not _cfg_icon.isNull():
                self.ptpv2_btn.setIcon(_cfg_icon)
                self.ptpv2_btn.setIconSize(QSize(16, 16))
        except Exception:
            pass
        self.ptpv2_btn.clicked.connect(self._open_ptpv2_config)
        config_layout.addWidget(self.ptpv2_btn)
        
        # ALSA config — same home resolution as InfernoConfig (config.py):
        # the actual user's home, never root's under sudo
        alsa_rc_path = get_actual_user_home() / ".asoundrc"
        self._asoundrc_path = alsa_rc_path
        self.asoundrc_btn = QPushButton("Open ~/.asoundrc")
        try:
            from PyQt6.QtGui import QIcon
            _rc_icon = QIcon("/usr/share/icons/Papirus/24x24/mimetypes/text-x-generic.svg")
            if not _rc_icon.isNull():
                self.asoundrc_btn.setIcon(_rc_icon)
                self.asoundrc_btn.setIconSize(QSize(16, 16))
        except Exception:
            pass
        self.asoundrc_btn.clicked.connect(self._open_asoundrc)
        config_layout.addWidget(self.asoundrc_btn)
        
        self.alsa_plugin_status = QLabel("Checking...")
        self.alsa_plugin_status.setStyleSheet("color: #aaa; font-size: 11px;")
        # Word wrap: same compact-layout reason as the PipeWire status
        # label above — the resolved text can carry a long plugin path.
        self.alsa_plugin_status.setWordWrap(True)
        config_layout.addWidget(self.alsa_plugin_status)

        # ── Actions ──────────────────────────────────────────────
        # Stacked vertically so the right column stays narrow enough
        # for the balanced two-column layout (side-by-side buttons made
        # the group ~380px wide and pushed the content past 760px).
        actions_group = QGroupBox("Actions")
        actions_layout = QVBoxLayout(actions_group)
        actions_layout.setSpacing(8)
        # 6px margins (compact layout, down from the 11px style
        # default): the save/reset buttons drive this group's width.
        actions_layout.setContentsMargins(6, 6, 6, 6)

        self.save_btn = QPushButton("Save Configuration")
        _save_icon = _asset_icon('save.svg')
        if not _save_icon.isNull():
            self.save_btn.setIcon(_save_icon)
            self.save_btn.setIconSize(QSize(16, 16))
        self.save_btn.setStyleSheet("""
            QPushButton { background-color: #4CAF50; color: white; border: none;
                          padding: 10px 20px; font-size: 13px; font-weight: bold;
                          border-radius: 4px; }
            QPushButton:hover { background-color: #45a049; }
        """)
        self.save_btn.clicked.connect(self.save_settings)
        actions_layout.addWidget(self.save_btn)

        self.reset_btn = QPushButton("Reset to Defaults")
        _reset_icon = _asset_icon('reset.svg')
        if not _reset_icon.isNull():
            self.reset_btn.setIcon(_reset_icon)
            self.reset_btn.setIconSize(QSize(16, 16))
        self.reset_btn.setStyleSheet("""
            QPushButton { background-color: #FF9800; color: white; border: none;
                          padding: 10px 20px; font-size: 13px; border-radius: 4px; }
            QPushButton:hover { background-color: #F57C00; }
        """)
        self.reset_btn.clicked.connect(self.reset_to_defaults)
        actions_layout.addWidget(self.reset_btn)

        # ── Latency Overview ────────────────────────────────────
        # Painted bar: the configured Inferno RX latency (green)
        # stacked on the estimated PipeWire graph round trip (blue).
        # The group tooltip carries the honesty note about inferno's
        # RX/TX asymmetry; the bar composes that note with the
        # estimate's scope disclosure. Values refresh on showEvent
        # (never at construction — see __init__).
        latency_group = QGroupBox("Latency Overview")
        latency_layout = QVBoxLayout(latency_group)
        latency_layout.setSpacing(4)
        self.latency_bar = LatencyBar()
        latency_group.setToolTip(_LATENCY_HONESTY_NOTE)
        self.latency_bar.set_context_note(_LATENCY_HONESTY_NOTE)
        latency_layout.addWidget(self.latency_bar)
        # Minimum width (not compactness): the overview's explanation
        # label wraps to ~9 lines at the ~178px the group got at the
        # minimal default window, pushing the right column's minimum
        # ~14px past the 621px content height the default window is
        # sized for (a vertical scrollbar appeared).  At 240px it wraps
        # to ~7 lines and the column's minimum stays under the
        # left-driven height — while remaining inside the ≤350px
        # right-column budget and the ≤720px/≤760px content budgets.
        latency_group.setMinimumWidth(240)

        # ── Right column container ──────────────────────────────
        # A nested column rather than flat grid rows: in a flat grid the
        # shared row heights inflated (row 2 = max(Advanced 171,
        # Config Files 214)) and pushed the content past the 560px
        # standard-window budget.  The nested stack keeps the columns'
        # heights independent and the fallback scroll area idle at
        # standard window sizes.
        right_column = QWidget()
        # Hard width cap (user-approved 50:50 rebalance): the old 240px
        # cap squeezed this column; ~340 keeps it in the 300–350px band
        # at every window size while the equal column stretch splits
        # the capped content roughly evenly with the left groups, and
        # the overview's labels wrap so nothing clips.
        right_column.setMaximumWidth(340)
        right_layout = QVBoxLayout(right_column)
        right_layout.setSpacing(12)
        right_layout.setContentsMargins(0, 0, 0, 0)
        # The Latency Overview group owns the TOP slot of this column
        # (the seam reserved for it); Actions and Config Files follow.
        right_layout.insertWidget(0, latency_group)
        right_layout.addWidget(actions_group)
        right_layout.addWidget(config_group)
        right_layout.addStretch()

        # ── Two-column arrangement ───────────────────────────────
        grid.addWidget(net_group, 0, 0)
        grid.addWidget(audio_group, 1, 0)
        grid.addWidget(adv_group, 2, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(right_column, 0, 1, 3, 1)

        # Column stretch 1:1 (user-approved 50:50 rebalance): the two
        # columns split the available width evenly — on wide windows
        # the right column tops out at its 340px cap and the spare
        # width collects in the left column (the denser one), while
        # compact viewports render both roughly equal.  The old 3:2
        # stretch kept the right column visibly narrower at every size.
        # Spare height still collects in the trailing stretch row so
        # the groups stay top-aligned.
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(3, 1)

        scroll.setWidget(content)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

        # Populate the interface list BEFORE load_settings() runs (from
        # __init__) — otherwise findData(saved) can never match and the
        # saved selection is lost.
        self._refresh_interfaces()

        # Initial checks
        QTimer.singleShot(500, self._check_system_status)

    def _configure_latency_spin(self, sb: QDoubleSpinBox) -> None:
        """Configure one latency editor.

        QDoubleSpinBox (not QSpinBox): QSpinBox is integer-only and
        cannot display decimals, while the approved contract asks for
        0.1 ms resolution. Display is milliseconds; storage stays
        integer nanoseconds via _ms_to_ns/_ns_to_ms.
        """
        sb.setDecimals(1)
        sb.setRange(1.0, 40.0)
        sb.setSingleStep(0.5)
        sb.setSuffix(" ms")
        sb.setValue(10.0)
        # Width cap (compact layout): the "40.0 ms" hint is ~72px at
        # default metrics so the cap never binds there; with fat
        # widget metrics the hint inflates and Qt clamps the layout
        # minimum to 120px, keeping the paired rows narrow.
        sb.setMaximumWidth(120)
        sb.setToolTip(
            "Inferno network latency for this direction, in milliseconds.\n\n"
            "Below ~1 ms RX underruns become likely — inferno does not clamp "
            "this value. Dante maximum is 40 ms.\n\n"
            "Takes effect after the next PTP start."
        )

    def _update_latency_warning(self) -> None:
        """Show the low-latency warning while either spinbox sits at the
        1.0 ms floor.

        The spinbox clamps at 1.0, so a value below 1.0 can never be
        entered: the floor is the closest reachable state and the honest
        place to surface the warning dynamically. The static tooltip
        carries the full wording at all times.
        """
        low = min(self.rx_latency.value(), self.tx_latency.value()) <= 1.0
        self.latency_warning.setVisible(low)

    def _refresh_latency_overview(self):
        """Update the Latency Overview bar.

        The Inferno segment shows the configured RX latency — the
        receive direction is the end-to-end path the user hears.  The
        PipeWire segment shows the estimated graph round trip from
        pw-metadata, or is absent ("unknown") when PipeWire cannot
        answer; read_pipewire_latency never raises.  The full result
        dict is forwarded as `details` so the bar can disclose the
        estimate's basis (quantum/rate/headroom).
        """
        pw = read_pipewire_latency()
        self.latency_bar.set_values(
            self.rx_latency.value(),
            pw["round_trip_ms"] if pw else None,
            details=pw,
        )

    def _ensure_latency_timer(self) -> QTimer:
        """The single live-refresh timer, created lazily on first show.

        One instance only: repeated showEvents reuse it instead of
        stacking timers; hideEvent/closeEvent stop it (showEvent
        restarts it).  Parent is the tab, so its lifetime follows the
        tab's.
        """
        if self._latency_timer is None:
            timer = QTimer(self)
            timer.setInterval(_LATENCY_REFRESH_MS)
            timer.timeout.connect(self._refresh_latency_overview)
            self._latency_timer = timer
        return self._latency_timer

    def showEvent(self, event):
        """Refresh the latency overview whenever the tab is shown, and
        keep it LIVE: a 5000 ms timer re-reads pw-metadata while the
        tab stays visible, so the estimate tracks quantum changes made
        while the tab is open (e.g. an app forcing the quantum)."""
        super().showEvent(event)
        self._refresh_latency_overview()
        timer = self._ensure_latency_timer()
        if not timer.isActive():
            timer.start()

    def hideEvent(self, event):
        """Stop the live refresh while the tab is hidden."""
        if self._latency_timer is not None:
            self._latency_timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        """Stop the live refresh when the tab closes."""
        if self._latency_timer is not None:
            self._latency_timer.stop()
        super().closeEvent(event)

    def _open_pw_override(self):
        """Open the PipeWire override in the user's session."""
        open_url_as_user(str(self._pw_override_path))

    def _open_ptpv1_config(self):
        """Open the PTPv1 statime config in the user's session."""
        open_url_as_user(str(self._ptpv1_path))

    def _open_ptpv2_config(self):
        """Open the PTPv2 statime config in the user's session."""
        open_url_as_user(str(self._ptpv2_path))

    def _open_asoundrc(self):
        """Open ~/.asoundrc in the user's session."""
        open_url_as_user(str(self._asoundrc_path))
    
    def _refresh_interfaces(self):
        """Refresh interface list.

        Population runs with the combo's signals blocked: adding items
        used to fire currentIndexChanged, emitting interface_changed for
        the transient first item, which propagated to the control tab
        and overwrote the saved interface there.  The previous selection
        is restored afterwards (same value, so nothing changes).
        """
        current = self.iface_combo.currentData()
        
        # Store IP info for each interface
        self._interface_ips = {}
        
        self.iface_combo.blockSignals(True)
        try:
            self.iface_combo.clear()
            interfaces = get_available_interfaces()
            if interfaces:
                for iface in interfaces:
                    ip = get_interface_ip(iface)
                    self._interface_ips[iface] = ip
                    display_text = f"{iface} ({ip})" if ip else f"{iface} (no IP)"
                    self.iface_combo.addItem(display_text, iface)
        finally:
            self.iface_combo.blockSignals(False)

        if current:
            idx = self.iface_combo.findData(current)
            if idx >= 0:
                self._restoring_iface = True
                try:
                    self.iface_combo.setCurrentIndex(idx)
                finally:
                    self._restoring_iface = False
        self._update_ip_display()
    
    def _on_iface_changed(self, index):
        """Handle interface change."""
        self._update_ip_display()
        iface = self.iface_combo.currentData()
        if iface:
            self.interface_changed.emit(iface)
            # BIND_IP follows the NIC (production DHCP fix — see
            # core.config.sync_bind_ip): a GENUINE user selection
            # change syncs the stored value immediately. Programmatic
            # restores (startup load, refresh, control-tab push) skip
            # the sync; the PTP start path covers those cases.
            # Silent by design: sync_bind_ip only logs, no popup, and
            # writes nothing when the stored value already matches.
            if not self._restoring_iface:
                sync_bind_ip(iface, self.inferno_config)
    
    def _on_ptp_version_toggled(self, button_id: int, checked: bool):
        """Handle PTP version radio button change."""
        if checked:
            version = 'v1' if button_id == 1 else 'v2'
            self.ptp_version_changed.emit(version)

    def _update_ip_display(self):
        """Update IP address display for selected interface."""
        iface = self.iface_combo.currentData()
        # Long names can be clipped in the closed combo (it sizes to
        # ~20 characters): the full item text rides the combo tooltip;
        # the popup shows it unclipped regardless.
        self.iface_combo.setToolTip(self.iface_combo.currentText())
        if iface:
            ip = get_interface_ip(iface)
            if ip:
                self.ip_display.setText(ip)
                self.ip_display.setStyleSheet("color: #4caf50; font-family: monospace;")
                # Auto-fill bind IP if empty
            else:
                self.ip_display.setText("(no IP assigned)")
                self.ip_display.setStyleSheet("color: #ffc107; font-family: monospace;")
        else:
            self.ip_display.setText("—")
            self.ip_display.setStyleSheet("color: #aaa;")

    def _check_system_status(self):
        """Check PipeWire override and ALSA plugin status."""
        # Check PipeWire override (same file the "Open" button targets,
        # resolved via the actual user's home)
        override_file = self._pw_override_path
        if override_file.exists():
            content = override_file.read_text()
            if "@clock" in content:
                self.pw_override_status.setText("✓ Configured correctly")
                self.pw_override_status.setStyleSheet("color: #4caf50; font-size: 11px;")
            else:
                self.pw_override_status.setText("⚠ File exists but missing @clock filter")
                self.pw_override_status.setStyleSheet("color: #ffc107; font-size: 11px;")
        else:
            self.pw_override_status.setText("✗ Not configured")
            self.pw_override_status.setStyleSheet("color: #f44336; font-size: 11px;")

        # Check ALSA plugin
        from inferno_gui.core.config import get_inferno_plugin, get_work_dir
        plugin_src = get_inferno_plugin()
        plugin_dst = Path("/usr/lib/x86_64-linux-gnu/alsa-lib/libasound_module_pcm_inferno.so")
        
        if plugin_dst.exists() or plugin_dst.is_symlink():
            try:
                target = plugin_dst.resolve()
                if target == plugin_src.resolve():
                    self.alsa_plugin_status.setText(f"✓ Installed and linked to {plugin_src}")
                    self.alsa_plugin_status.setStyleSheet("color: #4caf50; font-size: 11px;")
                else:
                    self.alsa_plugin_status.setText(f"⚠ Linked to different file: {target}")
                    self.alsa_plugin_status.setStyleSheet("color: #ffc107; font-size: 11px;")
            except Exception:
                self.alsa_plugin_status.setText("⚠ Symlink exists but target unclear")
                self.alsa_plugin_status.setStyleSheet("color: #ffc107; font-size: 11px;")
        elif plugin_src.exists():
            self.alsa_plugin_status.setText(f"⚠ Built but not installed (run install script)")
            self.alsa_plugin_status.setStyleSheet("color: #ffc107; font-size: 11px;")
        else:
            self.alsa_plugin_status.setText("✗ Not built (run installation script)")
            self.alsa_plugin_status.setStyleSheet("color: #f44336; font-size: 11px;")

    def _fix_pipewire_permissions(self):
        """Fix PipeWire @clock override."""
        override_dir = Path.home() / ".config/systemd/user/pipewire.service.d"
        override_file = override_dir / "override.conf"
        
        override_dir.mkdir(parents=True, exist_ok=True)
        override_file.write_text("""[Service]
SystemCallFilter=@clock
""")
        
        self.pw_override_status.setText("✓ Configured - restart PipeWire to apply")
        self.pw_override_status.setStyleSheet("color: #4caf50; font-size: 11px;")
        
        QMessageBox.information(
            self, "PipeWire Configuration Updated",
            "The @clock override has been added.\n\n"
            "Run the following to apply:\n"
            "  systemctl --user restart pipewire wireplumber\n\n"
            "Or reboot your system."
        )

    def _test_alsa_device(self):
        """Test inferno ALSA device."""
        import subprocess
        import os
        try:
            # Run as actual user so ~/.asoundrc is read correctly
            sudo_user = os.environ.get('SUDO_USER', 'jacob')
            result = subprocess.run(
                ['sudo', '-u', sudo_user, 'aplay', '-L'],
                capture_output=True, text=True, timeout=5
            )
            lines = [l for l in result.stdout.split('\n') if 'inferno' in l.lower()]
            if lines:
                msg = "Inferno ALSA device found:\n\n" + "\n".join(f"  {l.strip()}" for l in lines)
                QMessageBox.information(self, "ALSA Test Result", msg)
            else:
                QMessageBox.warning(
                    self, "ALSA Test Result",
                    "Inferno ALSA device NOT found in 'aplay -L'\n\n"
                    "Possible issues:\n"
                    "1. ALSA plugin not installed\n"
                    "2. ~/.asoundrc not configured correctly\n"
                    "3. PipeWire needs restart"
                )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to test ALSA: {e}")

    def _lock_log_level(self):
        """Log level is locked to TRACE: the log parser and PipeWire node
        automation require trace level (user-approved decision)."""
        self.log_level.setCurrentText("TRACE")
        self.log_level.setEnabled(False)

    def load_settings(self):
        """Load settings from config files and QSettings."""
        settings = user_settings("control")  # Use same group as control tab
        
        # Load inferno config
        if self.inferno_config.load():
            self.device_name.setText(self.inferno_config.name)
            idx = self.sample_rate.findData(self.inferno_config.sample_rate)
            if idx >= 0:
                self.sample_rate.setCurrentIndex(idx)
            self.tx_channels.setValue(self.inferno_config.tx_channels)
            self.rx_channels.setValue(self.inferno_config.rx_channels)
            # Latency: integer ns in the file → ms display. Missing or
            # malformed keys keep the 10 ms default (core/config.py).
            self.rx_latency.setValue(
                _ns_to_ms(self.inferno_config.get('rx_latency_ns')))
            self.tx_latency.setValue(
                _ns_to_ms(self.inferno_config.get('tx_latency_ns')))
        
        # Load interface selection
        saved_iface = settings.value("selected_interface", "", type=str)
        # Don't call _refresh_interfaces here - it's already called in _init_ui
        # Just restore the selection if we have a saved interface
        if saved_iface:
            idx = self.iface_combo.findData(saved_iface)
            if idx >= 0:
                self._restoring_iface = True
                try:
                    self.iface_combo.setCurrentIndex(idx)
                finally:
                    self._restoring_iface = False
        
        # Load PTP version
        ptp_ver = settings.value("ptp_version", "v2", type=str)
        if ptp_ver == 'v1':
            self.ptp_v1_radio.setChecked(True)
        else:
            self.ptp_v2_radio.setChecked(True)
        
        # Load advanced statime settings
        self.ptp_domain.setValue(settings.value("ptp_domain", 0, type=int))
        self.sync_interval.setValue(settings.value("sync_interval", 0, type=int))
        self.announce_interval.setValue(settings.value("announce_interval", 1, type=int))
        # Locked to trace: never restore a stored level (user-approved decision).
        self._lock_log_level()

    def _capture_original_values(self):
        """Capture current values as baseline for dirty tracking."""
        self._original_values = {
            'device_name': self.device_name.text(),
            'sample_rate': self.sample_rate.currentData(),
            'tx_channels': self.tx_channels.value(),
            'rx_channels': self.rx_channels.value(),
            'rx_latency': self.rx_latency.value(),
            'tx_latency': self.tx_latency.value(),
            'ptp_domain': self.ptp_domain.value(),
            'sync_interval': self.sync_interval.value(),
            'announce_interval': self.announce_interval.value(),
            'log_level': self.log_level.currentText(),
            'interface': self.iface_combo.currentData(),
            'ptp_version': 'v1' if self.ptp_v1_radio.isChecked() else 'v2',
        }
        self._dirty = False
        self.dirty_changed.emit(False)
    
    def _mark_dirty(self):
        """Mark settings as having unsaved changes."""
        if not self._dirty:
            self._dirty = True
            self.dirty_changed.emit(True)
            # Visual feedback - add asterisk to save button
            self.save_btn.setText("Save Configuration*")
            self.save_btn.setStyleSheet("""
                QPushButton { background-color: #FF9800; color: white; border: none;
                              padding: 10px 20px; font-size: 13px; font-weight: bold;
                              border-radius: 4px; }
                QPushButton:hover { background-color: #F57C00; }
            """)
    
    def _check_dirty(self) -> bool:
        """Check if current values differ from original."""
        current = {
            'device_name': self.device_name.text(),
            'sample_rate': self.sample_rate.currentData(),
            'tx_channels': self.tx_channels.value(),
            'rx_channels': self.rx_channels.value(),
            'rx_latency': self.rx_latency.value(),
            'tx_latency': self.tx_latency.value(),
            'ptp_domain': self.ptp_domain.value(),
            'sync_interval': self.sync_interval.value(),
            'announce_interval': self.announce_interval.value(),
            'log_level': self.log_level.currentText(),
            'interface': self.iface_combo.currentData(),
            'ptp_version': 'v1' if self.ptp_v1_radio.isChecked() else 'v2',
        }
        return current != self._original_values
    
    def _setup_dirty_tracking(self):
        """Connect all input widgets to dirty tracking."""
        widgets = [
            self.device_name,
            self.sample_rate,
            self.tx_channels,
            self.rx_channels,
            self.rx_latency,
            self.tx_latency,
            self.ptp_domain,
            self.sync_interval,
            self.announce_interval,
            self.log_level,
            self.iface_combo,
            self.ptp_v1_radio,
            self.ptp_v2_radio,
        ]
        for w in widgets:
            if hasattr(w, 'textChanged'):
                w.textChanged.connect(self._mark_dirty)
            elif hasattr(w, 'currentIndexChanged'):
                w.currentIndexChanged.connect(self._mark_dirty)
            elif hasattr(w, 'valueChanged'):
                w.valueChanged.connect(self._mark_dirty)
            elif hasattr(w, 'toggled'):
                w.toggled.connect(self._mark_dirty)
    
    def save_settings(self):
        """Save all settings to config files."""
        settings = user_settings("control")  # Use same group as control tab
        
        # Save inferno config
        self.inferno_config.set('name', self.device_name.text())
        self.inferno_config.set('sample_rate', self.sample_rate.currentData())
        self.inferno_config.set('tx_channels', self.tx_channels.value())
        self.inferno_config.set('rx_channels', self.rx_channels.value())
        # Latency: ms display → integer ns storage.
        self.inferno_config.set('rx_latency_ns', _ms_to_ns(self.rx_latency.value()))
        self.inferno_config.set('tx_latency_ns', _ms_to_ns(self.tx_latency.value()))

        # BIND_IP follows the NIC's current IP (production DHCP fix —
        # see core.config.sync_bind_ip): synced before persisting, so
        # the saved file always carries the selected interface's IP.
        # sync_bind_ip rewrites on its own only when the stored value
        # differs; the save below then persists everything in one go.
        iface = self.iface_combo.currentData()
        if iface:
            sync_bind_ip(iface, self.inferno_config)
        self.inferno_config.save()
        
        # Save interface
        if iface:
            settings.setValue("selected_interface", iface)
        
        # Save PTP version
        ptp_ver = 'v1' if self.ptp_v1_radio.isChecked() else 'v2'
        settings.setValue("ptp_version", ptp_ver)
        
        # Save advanced settings
        settings.setValue("ptp_domain", self.ptp_domain.value())
        settings.setValue("sync_interval", self.sync_interval.value())
        settings.setValue("announce_interval", self.announce_interval.value())
        # Locked to trace (user-approved decision).
        settings.setValue("log_level", "TRACE")
        # Running under sudo the settings file would stay root-owned;
        # flush and hand it back to the invoking user.
        chown_qsettings(settings)

        # Update statime configs with advanced settings
        self._update_statime_configs()

        # Re-assert the lock: save must never leave log_level editable.
        self._lock_log_level()
        
        # Notify control tab
        if self.control_tab:
            self.control_tab.set_interface(iface)
            self.control_tab.set_ptp_version(ptp_ver)
        
        self.settings_changed.emit()
        
        # Reset dirty state
        self._capture_original_values()
        
        QMessageBox.information(
            self, "Settings Saved",
            "Configuration saved successfully.\n\n"
            "Note: Changes to audio parameters (sample rate, channels) "
            "require restarting any applications using the Inferno device."
        )
    
    def has_unsaved_changes(self) -> bool:
        """Check if there are unsaved changes."""
        return self._dirty or self._check_dirty()
    
    def auto_save_if_dirty(self) -> bool:
        """Save settings if there are unsaved changes. Returns True if saved or no changes."""
        if self.has_unsaved_changes():
            self.save_settings()
            return True
        return True
    
    def _update_statime_configs(self):
        """Update both statime config files with advanced settings."""
        from inferno_gui.core.config import get_default_statime_config, StatimeConfig
        
        for ptp_ver in ['v1', 'v2']:
            config_path = get_default_statime_config(ptp_ver)
            if config_path.exists():
                try:
                    cfg = StatimeConfig(str(config_path))
                    if cfg.load():
                        # Handle both config formats (flat vs [global] section)
                        # Try flat format first (installed format)
                        if cfg.get('domain') is not None:
                            cfg.set('domain', self.ptp_domain.value())
                        else:
                            cfg.set('global.domain', self.ptp_domain.value())
                        
                        if cfg.get('loglevel') is not None:
                            cfg.set('loglevel', "trace")
                        elif cfg.get('global.log_level') is not None:
                            cfg.set('global.log_level', "trace")
                        else:
                            cfg.set('log_level', "trace")
                        
                        # Port settings - use hyphenated names as statime
                        # expects.  The installer templates write a [port]
                        # table (a dict) while hand-rolled configs often
                        # use a [[port]] array: update whichever shape the
                        # file has, in place, so the schema shape and key
                        # style survive the save.  A port whose shape
                        # matches neither (or anything unexpected) is
                        # skipped without raising: a shape mismatch must
                        # not block cfg.save() from writing the other
                        # changes (domain, log_level).
                        try:
                            ports = cfg.get('port')
                            if isinstance(ports, dict):
                                port_tables = [ports]
                            elif isinstance(ports, list):
                                port_tables = [
                                    p for p in ports if isinstance(p, dict)
                                ][:1]
                            else:
                                port_tables = []
                            for port in port_tables:
                                _set_port_interval(
                                    port, 'sync-interval',
                                    self.sync_interval.value())
                                _set_port_interval(
                                    port, 'announce-interval',
                                    self.announce_interval.value())
                        except Exception:
                            pass  # Port shape mismatch: still save the rest

                        cfg.save()
                except Exception:
                    pass  # Ignore config update errors

    def reset_to_defaults(self):
        """Reset all settings to defaults."""
        reply = QMessageBox.question(
            self, "Reset to Defaults",
            "Reset all settings to default values?\n"
            "This will overwrite ~/.asoundrc and statime configs.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.device_name.setText("Inferno")
            self.sample_rate.setCurrentText("48000 Hz")
            self.tx_channels.setValue(24)
            self.rx_channels.setValue(24)
            self.rx_latency.setValue(10.0)
            self.tx_latency.setValue(10.0)
            self.ptp_domain.setValue(0)
            self.sync_interval.setValue(0)
            self.announce_interval.setValue(1)
            self._lock_log_level()
            self.ptp_v2_radio.setChecked(True)
            self.save_settings()

    def set_interface(self, iface: str):
        """Set interface from control tab (programmatic — must not
        trigger a BIND_IP sync; the control tab's own paths cover it)."""
        idx = self.iface_combo.findData(iface)
        if idx >= 0:
            self._restoring_iface = True
            try:
                self.iface_combo.setCurrentIndex(idx)
            finally:
                self._restoring_iface = False

    def set_ptp_version(self, version: str):
        """Set PTP version from control tab."""
        if version == 'v1':
            self.ptp_v1_radio.setChecked(True)
        else:
            self.ptp_v2_radio.setChecked(True)

    def set_running_state(self, running: bool):
        """Disable/enable settings when inferno is running."""
        # Only update if state actually changes (idempotent).  When inferno
        # is running the widgets must be disabled, so the target state is
        # `not running` — the old guard compared against `running` itself
        # and returned early on the exact call that needed to disable.
        current_enabled = self.iface_combo.isEnabled()
        if current_enabled == (not running):
            return  # Already in correct state

        enabled = not running
        self.iface_combo.setEnabled(enabled)
        self.refresh_iface_btn.setEnabled(enabled)
        self.ptp_v1_radio.setEnabled(enabled)
        self.ptp_v2_radio.setEnabled(enabled)
        self.device_name.setEnabled(enabled)
        self.sample_rate.setEnabled(enabled)
        self.tx_channels.setEnabled(enabled)
        self.rx_channels.setEnabled(enabled)
        # Latency spinboxes lock while running, like the channels: they
        # only take effect after the next PTP start, and editing them
        # mid-run invites confusion about what is live.
        self.tx_latency.setEnabled(enabled)
        self.rx_latency.setEnabled(enabled)
        self.ptp_domain.setEnabled(enabled)
        self.sync_interval.setEnabled(enabled)
        self.announce_interval.setEnabled(enabled)
        # log_level stays disabled in every state (locked to trace).
        self.save_btn.setEnabled(enabled)
        self.reset_btn.setEnabled(enabled)
        
        # Visual indication
        if running:
            self.setStyleSheet("""
                QGroupBox { color: #888; }
                QLabel { color: #888; }
            """)
        else:
            self.setStyleSheet("")

    def has_unsaved_changes(self) -> bool:
        """Check if there are unsaved changes."""
        return self._dirty or self._check_dirty()
    
    def auto_save_if_dirty(self) -> bool:
        """Save settings if there are unsaved changes. Returns True if saved or no changes."""
        if self.has_unsaved_changes():
            self.save_settings()
            return True
        return True


# Need QTimer import
from PyQt6.QtCore import QTimer