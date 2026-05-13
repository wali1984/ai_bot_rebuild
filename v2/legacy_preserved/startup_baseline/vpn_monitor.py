#!/usr/bin/env python3
"""
VPN Connection Monitor for WMA AI Bot
Monitors PureVPN connection and sends Telegram alerts on disconnect/reconnect
"""
import os
import sys
import time
import subprocess
import asyncio
import logging
from pathlib import Path
from datetime import datetime
import requests

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from telegram_alerts import TelegramNotifier
from config import get_live_config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/vpn_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class VPNMonitor:
    """Monitor PureVPN connection status and alert on issues"""
    
    def __init__(self):
        self.telegram = None
        self.is_connected = False
        self.last_check_time = 0
        self.consecutive_failures = 0
        self.last_alert_time = 0
        self.alert_cooldown = 300  # 5 minutes between duplicate alerts
        
        # VPN detection settings
        self.vpn_interface = "tun-pure"
        self.vpn_process_names = ["openvpn", "purevpn", "pured-linux"]
        self.expected_dns_check_host = "api.binance.com"
        self.connection_test_urls = [
            "https://testnet.binancefuture.com",
            "https://api.binance.com/api/v3/ping",
        ]
        
        # Initialize Telegram
        try:
            config = get_live_config()
            self.telegram = TelegramNotifier(
                bot_token=config.TELEGRAM_BOT_TOKEN,
                bot_chat_id=config.TELEGRAM_CHAT_ID,
                channel_id=config.PRIVATE_CHANNEL_ID,
                portfolio_channel_id=config.PORTFOLIO_CHANNEL_ID,
                trade_channel_id=config.TRADE_CHANNEL_ID,
                ai_signals_channel_id=config.AI_SIGNALS_CHANNEL_ID
            )
            logger.info("✅ Telegram notifications enabled")
        except Exception as e:
            logger.warning(f"⚠️ Telegram notifications disabled: {e}")
        
        # Check initial status
        self._check_vpn_status()
        
    def _check_interface_exists(self) -> bool:
        """Check if VPN network interface exists"""
        try:
            result = subprocess.run(
                ['ip', 'addr', 'show', self.vpn_interface],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0 and 'UP' in result.stdout
        except Exception as e:
            logger.debug(f"Interface check failed: {e}")
            return False
    
    def _check_vpn_process(self) -> bool:
        """Check if VPN process is running"""
        try:
            result = subprocess.run(
                ['ps', 'aux'],
                capture_output=True,
                text=True,
                timeout=5
            )
            output = result.stdout.lower()
            return any(proc_name in output for proc_name in self.vpn_process_names)
        except Exception as e:
            logger.debug(f"Process check failed: {e}")
            return False
    
    def _check_dns_resolution(self) -> bool:
        """Check if DNS resolution works (VPN DNS should be working)"""
        try:
            import socket
            socket.setdefaulttimeout(5)
            ip = socket.gethostbyname(self.expected_dns_check_host)
            logger.debug(f"DNS resolved {self.expected_dns_check_host} → {ip}")
            return True
        except Exception as e:
            logger.debug(f"DNS check failed: {e}")
            return False
    
    def _check_connection_to_binance(self) -> bool:
        """Check if we can actually connect to Binance through VPN"""
        for url in self.connection_test_urls:
            try:
                response = requests.get(url, timeout=10)
                if response.status_code in [200, 201]:
                    logger.debug(f"✅ Connected to {url}")
                    return True
            except Exception as e:
                logger.debug(f"Connection test failed for {url}: {e}")
        return False
    
    def _get_vpn_ip(self) -> str:
        """Get current VPN IP address"""
        try:
            result = subprocess.run(
                ['ip', 'addr', 'show', self.vpn_interface],
                capture_output=True,
                text=True,
                timeout=5
            )
            # Parse IP from output like: "inet 10.5.14.27  netmask"
            for line in result.stdout.split('\n'):
                if 'inet ' in line and 'inet6' not in line:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        return parts[1].split('/')[0]
        except Exception as e:
            logger.debug(f"Failed to get VPN IP: {e}")
        return "unknown"
    
    def _check_vpn_status(self) -> dict:
        """
        Comprehensive VPN status check
        Returns dict with status details
        """
        status = {
            'connected': False,
            'interface_up': False,
            'process_running': False,
            'dns_working': False,
            'binance_reachable': False,
            'vpn_ip': None,
            'timestamp': time.time()
        }
        
        # Check 1: Interface exists and is UP
        status['interface_up'] = self._check_interface_exists()
        
        # Check 2: VPN process is running
        status['process_running'] = self._check_vpn_process()
        
        # Check 3: DNS resolution works
        if status['interface_up'] and status['process_running']:
            status['dns_working'] = self._check_dns_resolution()
        
        # Check 4: Can reach Binance (most important!)
        if status['dns_working']:
            status['binance_reachable'] = self._check_connection_to_binance()
        
        # Check 5: Get VPN IP
        if status['interface_up']:
            status['vpn_ip'] = self._get_vpn_ip()
        
        # Overall status: connected if Binance is reachable
        status['connected'] = status['binance_reachable']
        
        return status
    
    async def _send_telegram_alert(self, message: str, severity: str = "WARNING"):
        """Send Telegram alert (async)"""
        if not self.telegram:
            return
        
        try:
            await self.telegram.send_system_alert(message, severity)
            logger.info("📱 Telegram alert sent")
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")
    
    def _send_alert_sync(self, message: str, severity: str = "WARNING"):
        """Send Telegram alert (synchronous wrapper)"""
        if not self.telegram:
            return
        
        # Check cooldown to avoid spam
        current_time = time.time()
        if current_time - self.last_alert_time < self.alert_cooldown:
            logger.debug("Alert cooldown active, skipping duplicate alert")
            return
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._send_telegram_alert(message, severity))
            loop.close()
            self.last_alert_time = current_time
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
    
    def _handle_disconnect(self, status: dict):
        """Handle VPN disconnection"""
        logger.error("🚨 VPN DISCONNECTED!")
        logger.error(f"   Interface UP: {status['interface_up']}")
        logger.error(f"   Process running: {status['process_running']}")
        logger.error(f"   DNS working: {status['dns_working']}")
        logger.error(f"   Binance reachable: {status['binance_reachable']}")
        
        # Build diagnostic message
        issues = []
        if not status['interface_up']:
            issues.append("VPN interface (tun-pure) is DOWN")
        if not status['process_running']:
            issues.append("VPN process not running")
        if not status['dns_working']:
            issues.append("DNS resolution failed")
        if not status['binance_reachable']:
            issues.append("Cannot reach Binance")
        
        alert_message = f"""
🚨 <b>VPN DISCONNECTED</b>

<b>Status:</b> OFFLINE
<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

<b>Issues Detected:</b>
{'• ' + chr(10).join(issues)}

<b>Impact:</b>
⚠️ Trading connections may timeout
⚠️ Binance API requests will fail
⚠️ Trader may enter circuit breaker mode

<b>Action Required:</b>
1. Check PureVPN application
2. Reconnect to VPN server
3. Verify Binance connectivity
4. Restart trader if needed
        """.strip()
        
        self._send_alert_sync(alert_message, "CRITICAL")
    
    def _handle_reconnect(self, status: dict):
        """Handle VPN reconnection"""
        logger.info("✅ VPN RECONNECTED!")
        logger.info(f"   VPN IP: {status.get('vpn_ip', 'unknown')}")
        logger.info(f"   Binance reachable: {status['binance_reachable']}")
        
        alert_message = f"""
✅ <b>VPN RECONNECTED</b>

<b>Status:</b> ONLINE
<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
<b>VPN IP:</b> {status.get('vpn_ip', 'unknown')}

<b>Connection Status:</b>
• Interface: UP
• Process: Running
• DNS: Working
• Binance: Reachable ✓

<b>Trading can resume normally.</b>
        """.strip()
        
        self._send_alert_sync(alert_message, "INFO")
    
    def monitor(self, check_interval: int = 30):
        """
        Main monitoring loop
        
        Args:
            check_interval: Seconds between checks (default: 30)
        """
        logger.info("=" * 80)
        logger.info("🔍 VPN MONITOR STARTED")
        logger.info("=" * 80)
        logger.info(f"VPN Interface: {self.vpn_interface}")
        logger.info(f"Check Interval: {check_interval}s")
        logger.info(f"Telegram Alerts: {'Enabled' if self.telegram else 'Disabled'}")
        logger.info("=" * 80)
        
        # Initial status check
        status = self._check_vpn_status()
        self.is_connected = status['connected']
        
        if self.is_connected:
            logger.info(f"✅ Initial VPN status: CONNECTED (IP: {status.get('vpn_ip', 'unknown')})")
        else:
            logger.warning("⚠️ Initial VPN status: DISCONNECTED")
            self._handle_disconnect(status)
        
        # Monitoring loop
        try:
            while True:
                time.sleep(check_interval)
                
                # Check current status
                status = self._check_vpn_status()
                was_connected = self.is_connected
                now_connected = status['connected']
                
                # Detect state changes
                if was_connected and not now_connected:
                    # Disconnection detected
                    self.consecutive_failures += 1
                    logger.warning(f"⚠️ VPN check failed ({self.consecutive_failures}/3)")
                    
                    # Wait for 3 consecutive failures before alerting
                    if self.consecutive_failures >= 3:
                        self.is_connected = False
                        self._handle_disconnect(status)
                        self.consecutive_failures = 0
                    
                elif not was_connected and now_connected:
                    # Reconnection detected
                    self.is_connected = True
                    self.consecutive_failures = 0
                    self._handle_reconnect(status)
                    
                elif now_connected:
                    # Still connected - reset failure counter
                    self.consecutive_failures = 0
                    
                    # Log status every 10 minutes
                    if int(time.time()) % 600 < check_interval:
                        logger.info(f"✅ VPN healthy (IP: {status.get('vpn_ip', 'unknown')})")
                
                else:
                    # Still disconnected
                    self.consecutive_failures += 1
                    logger.warning(f"⚠️ VPN still disconnected ({self.consecutive_failures} checks)")
                
        except KeyboardInterrupt:
            logger.info("👋 VPN monitor stopped by user")
        except Exception as e:
            logger.error(f"❌ Fatal error in monitor: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            # Send crash notification
            crash_message = f"""
🚨 <b>VPN MONITOR CRASHED</b>

<b>Error:</b> {type(e).__name__}
<b>Message:</b> {str(e)[:200]}
<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

VPN monitoring has stopped. Manual restart required.
            """.strip()
            self._send_alert_sync(crash_message, "CRITICAL")
            raise


def main():
    """Main entry point"""
    # Create logs directory
    Path('logs').mkdir(exist_ok=True)
    
    # Get check interval from environment
    check_interval = int(os.getenv('VPN_CHECK_INTERVAL', '30'))
    
    logger.info("🚀 Starting VPN Monitor for WMA AI Bot")
    
    try:
        monitor = VPNMonitor()
        monitor.monitor(check_interval=check_interval)
    except KeyboardInterrupt:
        logger.info("👋 VPN monitor stopped")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
