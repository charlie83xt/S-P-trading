TRADING BOT AUTOMATION PLAN

Objective:
Turn Late 2013 MacBook Pro into dedicated trading appliance.

Daily Process:
1. Wake Mac automatically at 13:45 weekdays.
2. Launch trading script using launchd.
3. Activate Python virtual environment.
4. Launch Chrome/Selenium.
5. Complete manual Tradovate authentication if needed.
6. Run trading bot 14:00-19:00.
7. Save logs.
8. Close applications.
9. Put Mac to sleep.

Required Components:
- launchd
- pmset
- caffeinate
- Python venv
- Selenium
- Chrome

Benefits:
- No VS Code needed.
- No mouse jiggler needed.
- Automatic weekday operation.
- Automatic sleep after execution.
- Recoverable through logs.

Limitations:
- MFA / 2FA cannot be fully automated.
- Tradovate manual security checks may still require intervention.

Future Improvements:
- Persistent Chrome profile.
- Watchdog service.
- Telegram or email alerts.
- Hardware replacement with Mac Mini.