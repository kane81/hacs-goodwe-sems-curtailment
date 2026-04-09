## ⚠️ Requires hacs-custom-amber-integration

**This integration will not work without [hacs-custom-amber-integration](https://github.com/kane81/hacs-custom-amber-integration) installed first.**

Install that project from HACS before installing this one.

---

## ⚠️ Before You Install

This project uses the SEMS Portal API which is not publicly documented or officially supported. GoodWe may change or remove it at any time without notice. This project has no affiliation with GoodWe or SEMS. Use at your own risk — changing inverter output limits directly affects your solar system. The author accepts no responsibility for energy costs, equipment damage or system issues.

---

## 📋 Manual Steps Required After Install

After clicking Download you will need to:

1. Open **Terminal & SSH** and run the install script:
   ```
   bash /config/custom_components/sems_curtailment/install.sh
   ```
2. Add your SEMS credentials to `secrets.yaml` (Studio Code Server)
3. Restart Home Assistant

Full instructions are in the [README](https://github.com/kane81/hacs-goodwe-sems-curtailment#readme).

---

## ✅ Requirements

- **hacs-custom-amber-integration** installed and polling prices
- GoodWe solar inverter registered in SEMS Portal
- SEMS Portal account at [au.semsportal.com](https://au.semsportal.com)
- Home Assistant OS or Supervised
- Terminal & SSH add-on
