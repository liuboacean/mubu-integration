# demo.vhs — 录制 mubu-integration 往返保真演示 GIF
# 前置：brew install vhs   且已配置幕布凭据 (MUBU_PHONE / MUBU_PASSWORD)
# 运行：vhs demo.vhs   -> 生成 demo.gif
Output demo.gif
Set Shell "bash"
Set FontSize 18
Set Width 900
Set Height 520

Type "cat weekly.md"
Enter
Sleep 1.5s

Type "mubu import weekly.md"
Enter
Sleep 1.5s

Type "mubu export <doc_id> > out.md"
Enter
Sleep 1.5s

Type "diff weekly.md out.md"
Enter
Sleep 2s
