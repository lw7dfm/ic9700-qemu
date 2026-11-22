# Supply one DAT

No firmware is distributed here. Select **one** original or modified IC-9700
v1.50-compatible DAT. A modified input does not require an original DAT beside
it. The file may be stored here under any name or selected from another folder.

For official v1.50 obtain the update yourself from
https://www.icomjapan.com/support/firmware_driver/4424/, review Icom's terms and
extract `9700E150.dat`. Its SHA-256 is:
`001f34f2263bddebbf4a277d675918f1d68bef4c96537461d1fc495745ba8bb5`.

Run `bash INSTALL.sh --install-deps` initially, then `bash START.sh`, and select
your DAT once. The selected main supplies its own synthetic templates and its
ARM generates settings. No second firmware, stock seed or stock cache is used
for a candidate. No input is edited and no installable DAT is generated.

Do not commit or redistribute DATs, decoded firmware, native UI screenshots,
flash images, EEPROM or calibration. Generated test data stays in ignored
`work/`; `.gitignore` is a safeguard, not legal permission.
