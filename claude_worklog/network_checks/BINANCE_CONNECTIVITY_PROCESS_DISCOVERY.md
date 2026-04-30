# Binance Connectivity Process Discovery
Generated: 2026-04-29T23:28:13-04:00

## Relevant processes
root        1910  0.0  0.1 316148 152660 ?       Ss   Apr25   0:00 /usr/bin/python3 -m proton.vpn.daemon
redis       1925 31.0 12.6 22529872 16307932 ?   Rsl  Apr25 1853:16 /usr/bin/redis-server 127.0.0.1:6379
root        1931  0.0  0.0 118060 24132 ?        Ssl  Apr25   0:00 /usr/bin/python3 /usr/share/unattended-upgrades/unattended-upgrade-shutdown --wait-for-signal
wali        5131  0.4  0.4 18888852 535816 ?     Sl   Apr25  26:11 python3 -m rl.orchestrator_worker
root      130251  0.0  0.0   2712  2124 ?        Ss   Apr26   0:00 fusermount3 -o rw,nosuid,nodev,fsname=portal,auto_unmount,subtype=portal -- /run/user/1000/doc
wali      133521  0.0  0.1 1461358676 143836 ?   Sl   Apr26   0:22 /proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --crashpad-handler-pid=133395 --enable-crash-reporter=840f1fb3-4e6c-4da7-a3b1-c054c633c521,no_channel --user-data-dir=/home/wali/.config/Cursor --standard-schemes=vscode-webview,vscode-file --enable-sandbox --secure-schemes=vscode-webview,vscode-file,sentry-ipc --bypasscsp-schemes=sentry-ipc --cors-schemes=vscode-webview,vscode-file,sentry-ipc --fetch-schemes=vscode-webview,vscode-file,sentry-ipc --service-worker-schemes=vscode-webview --code-cache-schemes=vscode-webview,vscode-file --shared-files=v8_context_snapshot_data:100 --field-trial-handle=3,i,6782813967262861978,1761961943262673250,262144 --enable-features=DocumentPolicyIncludeJSCallStacksInCrashReports,PdfUseShowSaveFilePicker --disable-features=CalculateNativeWinOcclusion,LocalNetworkAccessChecks,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708990997080739
wali      133522 30.3  0.0 1461375476 129016 ?   Sl   Apr26 1317:39 /proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --crashpad-handler-pid=133395 --enable-crash-reporter=840f1fb3-4e6c-4da7-a3b1-c054c633c521,no_channel --user-data-dir=/home/wali/.config/Cursor --standard-schemes=vscode-webview,vscode-file --enable-sandbox --secure-schemes=vscode-webview,vscode-file,sentry-ipc --bypasscsp-schemes=sentry-ipc --cors-schemes=vscode-webview,vscode-file,sentry-ipc --fetch-schemes=vscode-webview,vscode-file,sentry-ipc --service-worker-schemes=vscode-webview --code-cache-schemes=vscode-webview,vscode-file --shared-files=v8_context_snapshot_data:100 --field-trial-handle=3,i,6782813967262861978,1761961943262673250,262144 --enable-features=DocumentPolicyIncludeJSCallStacksInCrashReports,PdfUseShowSaveFilePicker --disable-features=CalculateNativeWinOcclusion,LocalNetworkAccessChecks,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708991934122588
wali      133523  0.9  0.1 1478141168 253920 ?   Sl   Apr26  40:22 /proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --dns-result-order=ipv4first --experimental-network-inspection --inspect-port=0 --crashpad-handler-pid=133395 --enable-crash-reporter=840f1fb3-4e6c-4da7-a3b1-c054c633c521,no_channel --user-data-dir=/home/wali/.config/Cursor --standard-schemes=vscode-webview,vscode-file --enable-sandbox --secure-schemes=vscode-webview,vscode-file,sentry-ipc --bypasscsp-schemes=sentry-ipc --cors-schemes=vscode-webview,vscode-file,sentry-ipc --fetch-schemes=vscode-webview,vscode-file,sentry-ipc --service-worker-schemes=vscode-webview --code-cache-schemes=vscode-webview,vscode-file --shared-files=v8_context_snapshot_data:100 --field-trial-handle=3,i,6782813967262861978,1761961943262673250,262144 --enable-features=DocumentPolicyIncludeJSCallStacksInCrashReports,PdfUseShowSaveFilePicker --disable-features=CalculateNativeWinOcclusion,LocalNetworkAccessChecks,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708992871164437
wali      133619  0.0  0.0 1478161072 110584 ?   Sl   Apr26   3:52 /proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --crashpad-handler-pid=133395 --enable-crash-reporter=840f1fb3-4e6c-4da7-a3b1-c054c633c521,no_channel --user-data-dir=/home/wali/.config/Cursor --standard-schemes=vscode-webview,vscode-file --enable-sandbox --secure-schemes=vscode-webview,vscode-file,sentry-ipc --bypasscsp-schemes=sentry-ipc --cors-schemes=vscode-webview,vscode-file,sentry-ipc --fetch-schemes=vscode-webview,vscode-file,sentry-ipc --service-worker-schemes=vscode-webview --code-cache-schemes=vscode-webview,vscode-file --shared-files=v8_context_snapshot_data:100 --field-trial-handle=3,i,6782813967262861978,1761961943262673250,262144 --enable-features=DocumentPolicyIncludeJSCallStacksInCrashReports,PdfUseShowSaveFilePicker --disable-features=CalculateNativeWinOcclusion,LocalNetworkAccessChecks,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708993808206286
wali      133660  0.9  2.8 1461567404 3732904 ?  Sl   Apr26  39:22 /proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --dns-result-order=ipv4first --experimental-network-inspection --inspect-port=0 --crashpad-handler-pid=133395 --enable-crash-reporter=840f1fb3-4e6c-4da7-a3b1-c054c633c521,no_channel --user-data-dir=/home/wali/.config/Cursor --standard-schemes=vscode-webview,vscode-file --enable-sandbox --secure-schemes=vscode-webview,vscode-file,sentry-ipc --bypasscsp-schemes=sentry-ipc --cors-schemes=vscode-webview,vscode-file,sentry-ipc --fetch-schemes=vscode-webview,vscode-file,sentry-ipc --service-worker-schemes=vscode-webview --code-cache-schemes=vscode-webview,vscode-file --shared-files=v8_context_snapshot_data:100 --field-trial-handle=3,i,6782813967262861978,1761961943262673250,262144 --enable-features=DocumentPolicyIncludeJSCallStacksInCrashReports,PdfUseShowSaveFilePicker --disable-features=CalculateNativeWinOcclusion,LocalNetworkAccessChecks,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708994745248135
wali      133661  0.4  0.1 1461359636 205064 ?   Sl   Apr26  19:52 /proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --dns-result-order=ipv4first --experimental-network-inspection --inspect-port=0 --crashpad-handler-pid=133395 --enable-crash-reporter=840f1fb3-4e6c-4da7-a3b1-c054c633c521,no_channel --user-data-dir=/home/wali/.config/Cursor --standard-schemes=vscode-webview,vscode-file --enable-sandbox --secure-schemes=vscode-webview,vscode-file,sentry-ipc --bypasscsp-schemes=sentry-ipc --cors-schemes=vscode-webview,vscode-file,sentry-ipc --fetch-schemes=vscode-webview,vscode-file,sentry-ipc --service-worker-schemes=vscode-webview --code-cache-schemes=vscode-webview,vscode-file --shared-files=v8_context_snapshot_data:100 --field-trial-handle=3,i,6782813967262861978,1761961943262673250,262144 --enable-features=DocumentPolicyIncludeJSCallStacksInCrashReports,PdfUseShowSaveFilePicker --disable-features=CalculateNativeWinOcclusion,LocalNetworkAccessChecks,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708995682289984
wali      133743  0.1  0.1 12162684 150076 ?     Sl   Apr26   6:19 /usr/share/cursor/resources/app/resources/helpers/node --max-old-space-size=32768 /home/wali/.cursor/extensions/anysphere.cursorpyright-1.0.10/dist/server.js --cancellationReceive=file:b161daf9d5332283bcf84325ecbf36e4ff99f94ffb --node-ipc --clientProcessId=133523
wali      133898  0.0  0.0 1476315900 97860 ?    Sl   Apr26   3:08 /usr/share/cursor/cursor /usr/share/cursor/resources/app/extensions/markdown-language-features/dist/serverWorkerMain --node-ipc --clientProcessId=133523
wali      137941  0.0  0.1 1461341164 154080 ?   Sl   Apr26   3:10 /proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --crashpad-handler-pid=137816 --enable-crash-reporter=56273a96-79c8-475b-8a6c-947b09a8bcf4,no_channel --user-data-dir=/home/wali/.config/Code --standard-schemes=vscode-webview,vscode-file --enable-sandbox --secure-schemes=vscode-webview,vscode-file --cors-schemes=vscode-webview,vscode-file --fetch-schemes=vscode-webview,vscode-file --service-worker-schemes=vscode-webview --code-cache-schemes=vscode-webview,vscode-file --shared-files=v8_context_snapshot_data:100 --field-trial-handle=3,i,8506312766848220127,17544181818425766856,262144 --enable-features=DocumentPolicyIncludeJSCallStacksInCrashReports,EarlyEstablishGpuChannel,EstablishGpuChannelAsync --disable-features=CalculateNativeWinOcclusion,LocalNetworkAccessChecks,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708990997080739
wali      137942 29.9  0.1 1461358044 144720 ?   Sl   Apr26 1300:31 /proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --crashpad-handler-pid=137816 --enable-crash-reporter=56273a96-79c8-475b-8a6c-947b09a8bcf4,no_channel --user-data-dir=/home/wali/.config/Code --standard-schemes=vscode-webview,vscode-file --enable-sandbox --secure-schemes=vscode-webview,vscode-file --cors-schemes=vscode-webview,vscode-file --fetch-schemes=vscode-webview,vscode-file --service-worker-schemes=vscode-webview --code-cache-schemes=vscode-webview,vscode-file --shared-files=v8_context_snapshot_data:100 --field-trial-handle=3,i,8506312766848220127,17544181818425766856,262144 --enable-features=DocumentPolicyIncludeJSCallStacksInCrashReports,EarlyEstablishGpuChannel,EstablishGpuChannelAsync --disable-features=CalculateNativeWinOcclusion,LocalNetworkAccessChecks,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708991934122588
wali      138052  0.1  0.0 1478250188 123032 ?   Sl   Apr26   7:15 /proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --crashpad-handler-pid=137816 --enable-crash-reporter=56273a96-79c8-475b-8a6c-947b09a8bcf4,no_channel --user-data-dir=/home/wali/.config/Code --standard-schemes=vscode-webview,vscode-file --enable-sandbox --secure-schemes=vscode-webview,vscode-file --cors-schemes=vscode-webview,vscode-file --fetch-schemes=vscode-webview,vscode-file --service-worker-schemes=vscode-webview --code-cache-schemes=vscode-webview,vscode-file --shared-files=v8_context_snapshot_data:100 --field-trial-handle=3,i,8506312766848220127,17544181818425766856,262144 --enable-features=DocumentPolicyIncludeJSCallStacksInCrashReports,EarlyEstablishGpuChannel,EstablishGpuChannelAsync --disable-features=CalculateNativeWinOcclusion,LocalNetworkAccessChecks,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708993808206286
wali      142712 22.8  0.5 19867028 735892 pts/6 Sl   Apr26 989:26 python3 ingest/live_binance.py
wali      142970  0.0  0.3 18963084 437868 pts/7 Sl   Apr26   0:11 python3 ingest/live_binance_liquidations.py
wali      143125 85.7  3.8 101135528 5002976 pts/8 Sl Apr26 3717:02 python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features
wali      143308  0.2  0.4 19912364 607252 pts/9 Sl   Apr26   9:55 python3 trading/trader.py
wali      143507  0.0  0.0  25828 12428 pts/8    S    Apr26   0:00 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.resource_tracker import main;main(77)
wali      143725  1.6  0.0  97872 38788 pts/8    S    Apr26  72:41 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=80) --multiprocessing-fork
wali      143726  1.6  0.0  97848 40996 pts/8    S    Apr26  73:39 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=83) --multiprocessing-fork
wali      143727  1.6  0.0  97872 41036 pts/8    S    Apr26  73:06 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=86) --multiprocessing-fork
wali      143728  1.6  0.0  97860 40916 pts/8    S    Apr26  73:12 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=89) --multiprocessing-fork
wali      143729  1.6  0.0  97564 39220 pts/8    S    Apr26  73:24 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=92) --multiprocessing-fork
wali      143730  1.6  0.0  97860 41876 pts/8    S    Apr26  73:25 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=95) --multiprocessing-fork
wali      143731  1.6  0.0  97848 42296 pts/8    S    Apr26  73:31 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=98) --multiprocessing-fork
wali      143732  1.6  0.0  97860 40760 pts/8    S    Apr26  73:43 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=101) --multiprocessing-fork
wali      143734  1.6  0.0  97860 41804 pts/8    S    Apr26  73:39 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=105) --multiprocessing-fork
wali      143735  1.6  0.0  97860 41040 pts/8    S    Apr26  73:09 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=108) --multiprocessing-fork
wali      143736  1.6  0.0  97860 40336 pts/8    S    Apr26  73:38 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=111) --multiprocessing-fork
wali      143737  1.6  0.0  97872 39864 pts/8    S    Apr26  73:39 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=114) --multiprocessing-fork
wali      143738  1.6  0.0  97848 41252 pts/8    S    Apr26  73:37 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=117) --multiprocessing-fork
wali      143739  1.6  0.0  97848 40936 pts/8    S    Apr26  72:45 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=120) --multiprocessing-fork
wali      143740  1.6  0.0  97880 39912 pts/8    S    Apr26  73:07 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=123) --multiprocessing-fork
wali      143741  1.6  0.0  97856 40924 pts/8    S    Apr26  73:01 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=126) --multiprocessing-fork
wali      143742  1.6  0.0  97880 41740 pts/8    S    Apr26  72:54 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=129) --multiprocessing-fork
wali      143743  1.6  0.0  97840 41100 pts/8    S    Apr26  72:42 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=132) --multiprocessing-fork
wali      143744  1.6  0.0  97860 39608 pts/8    S    Apr26  72:31 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=135) --multiprocessing-fork
wali      143745  1.6  0.0  97860 39884 pts/8    S    Apr26  71:57 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=138) --multiprocessing-fork
wali      143746  1.6  0.0  97872 40368 pts/8    S    Apr26  71:41 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=141) --multiprocessing-fork
wali      143747  1.6  0.0  96844 39936 pts/8    S    Apr26  72:07 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=144) --multiprocessing-fork
wali      143748  1.6  0.0  97848 40236 pts/8    S    Apr26  72:25 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=147) --multiprocessing-fork
wali      143749  1.6  0.0  97848 40916 pts/8    S    Apr26  71:39 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=150) --multiprocessing-fork
wali      143750  1.6  0.0  97848 39884 pts/8    S    Apr26  72:10 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=153) --multiprocessing-fork
wali      143751  1.6  0.0  97852 41700 pts/8    S    Apr26  72:46 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=156) --multiprocessing-fork
wali      143752  1.6  0.0  97860 39516 pts/8    S    Apr26  72:47 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=159) --multiprocessing-fork
wali      143753  1.6  0.0  97860 40508 pts/8    S    Apr26  72:20 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=162) --multiprocessing-fork
wali      143754  1.6  0.0  97868 41836 pts/8    S    Apr26  72:07 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=165) --multiprocessing-fork
wali      143755  2.8  0.0  97872 41640 pts/8    S    Apr26 123:22 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=168) --multiprocessing-fork
wali      143756  1.6  0.0  97848 40020 pts/8    S    Apr26  71:43 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=171) --multiprocessing-fork
wali      143757  2.5  0.0  97860 41912 pts/8    S    Apr26 112:35 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=174) --multiprocessing-fork
wali      143758  2.5  0.0  97852 41516 pts/8    S    Apr26 111:08 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=177) --multiprocessing-fork
wali      143759  2.5  0.0  97880 41236 pts/8    S    Apr26 110:04 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=180) --multiprocessing-fork
wali      143760  2.5  0.0  97860 38796 pts/8    S    Apr26 110:17 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=183) --multiprocessing-fork
wali      143761  2.5  0.0  97860 41060 pts/8    S    Apr26 112:12 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=186) --multiprocessing-fork
wali      143762  2.7  0.0  97860 40864 pts/8    S    Apr26 117:16 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=189) --multiprocessing-fork
wali      143763  2.8  0.0  97564 40612 pts/8    S    Apr26 122:39 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=192) --multiprocessing-fork
wali      143764  2.8  0.0  97848 38724 pts/8    S    Apr26 122:50 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=195) --multiprocessing-fork
wali      143765  2.8  0.0  97848 41488 pts/8    S    Apr26 125:11 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=198) --multiprocessing-fork
wali      143766  2.7  0.0  97544 42460 pts/8    S    Apr26 117:19 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=201) --multiprocessing-fork
wali      143767  2.9  0.0  97544 36896 pts/8    S    Apr26 128:25 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=204) --multiprocessing-fork
wali      143768  2.8  0.0  97872 40616 pts/8    S    Apr26 122:09 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=207) --multiprocessing-fork
wali      143769  2.5  0.0  97860 42060 pts/8    S    Apr26 111:20 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=210) --multiprocessing-fork
wali      143770  2.7  0.0  97860 41248 pts/8    S    Apr26 117:57 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=213) --multiprocessing-fork
wali      143771  2.5  0.0  97860 41864 pts/8    S    Apr26 109:13 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=217) --multiprocessing-fork
wali      143772  2.8  0.0  97860 41656 pts/8    S    Apr26 123:37 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=219) --multiprocessing-fork
wali      143773  2.8  0.0  97840 39860 pts/8    S    Apr26 124:12 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=222) --multiprocessing-fork
wali      143774  2.8  0.0  97856 42104 pts/8    S    Apr26 124:16 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=222) --multiprocessing-fork
wali      143775  2.8  0.0  97860 42656 pts/8    S    Apr26 121:45 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=225) --multiprocessing-fork
wali      143776  1.6  0.0  97860 43316 pts/8    S    Apr26  72:20 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=232) --multiprocessing-fork
wali      143777  1.6  0.0  97860 41904 pts/8    S    Apr26  72:32 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=235) --multiprocessing-fork
wali      143778  1.6  0.0  97860 42452 pts/8    S    Apr26  72:27 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=237) --multiprocessing-fork
wali      143779  1.6  0.0  97872 41956 pts/8    S    Apr26  72:00 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=240) --multiprocessing-fork
wali      143780  4.9  0.0  97848 42728 pts/8    S    Apr26 214:40 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=243) --multiprocessing-fork
wali      143781  1.6  0.0  97860 42092 pts/8    S    Apr26  72:31 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=246) --multiprocessing-fork
wali      143782  4.6  0.0  97848 41700 pts/8    S    Apr26 202:48 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=249) --multiprocessing-fork
wali      143783  4.6  0.0  97872 42100 pts/8    S    Apr26 202:32 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=252) --multiprocessing-fork
wali      143784  4.6  0.0  97872 39356 pts/8    S    Apr26 201:58 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=255) --multiprocessing-fork
wali      143785  4.7  0.0  97860 40552 pts/8    S    Apr26 204:52 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=258) --multiprocessing-fork
wali      143786  4.4  0.0  97872 41016 pts/8    S    Apr26 191:23 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=261) --multiprocessing-fork
wali      143787  4.4  0.0  96848 42628 pts/8    S    Apr26 194:32 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=264) --multiprocessing-fork
wali      143788  4.6  0.0  97848 41736 pts/8    S    Apr26 201:46 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=267) --multiprocessing-fork
wali      143789  4.6  0.0  97856 40848 pts/8    S    Apr26 201:51 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=270) --multiprocessing-fork
wali      143790  4.7  0.0  97848 39316 pts/8    S    Apr26 207:15 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=273) --multiprocessing-fork
wali      143791  4.6  0.0  97848 40276 pts/8    S    Apr26 200:24 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=276) --multiprocessing-fork
wali      143792  4.9  0.0  97856 40240 pts/8    S    Apr26 214:51 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=279) --multiprocessing-fork
wali      143793  4.7  0.0  97808 40508 pts/8    S    Apr26 204:19 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=282) --multiprocessing-fork
wali      143794  4.5  0.0  97544 40652 pts/8    S    Apr26 195:55 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=285) --multiprocessing-fork
wali      143795  4.6  0.0  97880 41432 pts/8    S    Apr26 201:36 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=288) --multiprocessing-fork
wali      143796  4.5  0.0  97848 40920 pts/8    S    Apr26 195:46 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=291) --multiprocessing-fork
wali      143797  4.7  0.0  97840 39756 pts/8    S    Apr26 207:48 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=294) --multiprocessing-fork
wali      143798  4.7  0.0  97856 41456 pts/8    S    Apr26 206:48 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=297) --multiprocessing-fork
wali      143799  4.8  0.0  97848 41660 pts/8    S    Apr26 210:04 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=300) --multiprocessing-fork
wali      143800  4.7  0.0  97856 41584 pts/8    S    Apr26 206:09 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=303) --multiprocessing-fork
wali      143801  1.6  0.0  97868 42336 pts/8    S    Apr26  73:39 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=306) --multiprocessing-fork
wali      143802  1.6  0.0  97860 41588 pts/8    S    Apr26  73:31 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=309) --multiprocessing-fork
wali      143803  1.6  0.0  97852 41044 pts/8    S    Apr26  73:01 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=312) --multiprocessing-fork
wali      143804  1.7  0.0  97860 41940 pts/8    S    Apr26  74:18 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=315) --multiprocessing-fork
wali      143805  5.5  0.0  97808 41672 pts/8    S    Apr26 240:05 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=318) --multiprocessing-fork
wali      143806  1.6  0.0  97848 41208 pts/8    S    Apr26  73:43 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=321) --multiprocessing-fork
wali      143807  5.4  0.0  97856 38224 pts/8    S    Apr26 236:06 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=324) --multiprocessing-fork
wali      143808  5.3  0.0  97848 41544 pts/8    S    Apr26 231:10 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=327) --multiprocessing-fork
wali      143809  5.4  0.0  97872 42188 pts/8    R    Apr26 234:38 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=330) --multiprocessing-fork
wali      143810  5.4  0.0  97880 40500 pts/8    R    Apr26 236:08 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=333) --multiprocessing-fork
wali      143811  5.0  0.0  97860 41600 pts/8    R    Apr26 218:43 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=336) --multiprocessing-fork
wali      143812  5.0  0.0  97856 40692 pts/8    R    Apr26 220:35 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=339) --multiprocessing-fork
wali      143813  5.0  0.0  97856 41736 pts/8    R    Apr26 219:26 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=342) --multiprocessing-fork
wali      143814  5.1  0.0  97872 40296 pts/8    R    Apr26 222:10 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=345) --multiprocessing-fork
wali      143815  5.2  0.0  97880 41036 pts/8    R    Apr26 227:48 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=348) --multiprocessing-fork
wali      143816  5.1  0.0  97872 40080 pts/8    R    Apr26 221:10 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=351) --multiprocessing-fork
wali      143817  5.4  0.0  97880 40172 pts/8    S    Apr26 235:37 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=354) --multiprocessing-fork
wali      143818  5.0  0.0  97872 40368 pts/8    R    Apr26 220:42 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=357) --multiprocessing-fork
wali      143819  4.9  0.0  97848 40928 pts/8    S    Apr26 216:28 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=360) --multiprocessing-fork
wali      143820  5.0  0.0  97848 41700 pts/8    S    Apr26 219:26 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=363) --multiprocessing-fork
wali      143821  5.0  0.0  97872 41024 pts/8    S    Apr26 218:32 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=366) --multiprocessing-fork
wali      143822  5.0  0.0  96824 40220 pts/8    S    Apr26 221:05 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=369) --multiprocessing-fork
wali      143823  5.1  0.0  97848 40492 pts/8    S    Apr26 223:40 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=372) --multiprocessing-fork
wali      143824  5.1  0.0  97848 41252 pts/8    S    Apr26 223:26 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=375) --multiprocessing-fork
wali      143825  5.1  0.0  96848 42468 pts/8    S    Apr26 221:10 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=378) --multiprocessing-fork
wali      143826  1.6  0.0  97872 39896 pts/8    S    Apr26  73:32 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=381) --multiprocessing-fork
wali      143827  1.6  0.0  97872 37392 pts/8    S    Apr26  73:26 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=384) --multiprocessing-fork
wali      143828  1.7  0.0  97880 41264 pts/8    S    Apr26  73:50 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=387) --multiprocessing-fork
wali      143829  1.6  0.0  97860 42080 pts/8    S    Apr26  72:41 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=390) --multiprocessing-fork
wali      143830  5.8  0.0  97856 38940 pts/8    S    Apr26 252:57 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=393) --multiprocessing-fork
wali      143831  1.7  0.0  97856 40160 pts/8    S    Apr26  73:43 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=396) --multiprocessing-fork
wali      143832  5.6  0.0  97856 40628 pts/8    S    Apr26 244:37 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=399) --multiprocessing-fork
wali      143833  5.5  0.0  97856 40768 pts/8    S    Apr26 242:28 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=402) --multiprocessing-fork
wali      143834  5.6  0.0  97848 41116 pts/8    S    Apr26 242:54 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=405) --multiprocessing-fork
wali      143835  5.6  0.0  97860 40352 pts/8    S    Apr26 245:54 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=408) --multiprocessing-fork
wali      143836  5.2  0.0  97860 40340 pts/8    S    Apr26 226:54 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=411) --multiprocessing-fork
wali      143837  5.1  0.0  97856 39956 pts/8    S    Apr26 225:12 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=414) --multiprocessing-fork
wali      143838  5.1  0.0  97872 40964 pts/8    S    Apr26 222:23 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=417) --multiprocessing-fork
wali      143839  5.1  0.0  97564 41400 pts/8    S    Apr26 223:44 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=420) --multiprocessing-fork
wali      143840  5.1  0.0  97840 40124 pts/8    S    Apr26 223:44 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=423) --multiprocessing-fork
wali      143841  5.1  0.0  97872 41228 pts/8    S    Apr26 222:05 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=426) --multiprocessing-fork
wali      143842  5.3  0.0  97856 40104 pts/8    S    Apr26 232:35 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=429) --multiprocessing-fork
wali      143843  5.1  0.0  97544 40504 pts/8    S    Apr26 222:03 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=432) --multiprocessing-fork
wali      143844  5.2  0.0  97856 39592 pts/8    S    Apr26 226:32 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=435) --multiprocessing-fork
wali      143845  5.1  0.0  97872 41132 pts/8    S    Apr26 222:03 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=438) --multiprocessing-fork
wali      143846  5.0  0.0  97872 41320 pts/8    S    Apr26 220:21 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=441) --multiprocessing-fork
wali      143847  5.0  0.0  97848 39512 pts/8    S    Apr26 219:26 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=444) --multiprocessing-fork
wali      143848  5.1  0.0  97848 40260 pts/8    S    Apr26 224:06 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=447) --multiprocessing-fork
wali      143849  5.0  0.0  97872 41100 pts/8    S    Apr26 220:52 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=451) --multiprocessing-fork
wali      143850  5.1  0.0  97748 42736 pts/8    S    Apr26 221:54 /home/wali/Desktop/AI BOT/venv/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=78, pipe_handle=457) --multiprocessing-fork
wali      146536  0.0  0.0   8324  2112 pts/12   S+   Apr26   0:01 tail -f Desktop/AI BOT/logs/trader.log
wali      146635  0.0  0.0   8324  2108 pts/13   S+   Apr26   0:00 tail -f Desktop/AI BOT/logs/orchestrator_worker.log
wali      146815 15.1  0.4 17471716 525604 ?     Sl   Apr26 657:23 python3 ingest/live_coinank.py
wali      146816  0.0  0.3 17210412 395456 ?     Sl   Apr26   1:24 python3 ingest/liquidation_levels_engine.py
wali      146817  1.8  0.3 18743196 483624 ?     Sl   Apr26  79:11 python3 ingest/live_technical_analysis.py
wali      147111  0.0  0.3 17204044 508504 pts/16 Sl+ Apr26   2:17 python3 Desktop/AI BOT/scripts/monitor_trainer_prices.py
wali      148568  0.0  0.3 17436872 415068 pts/18 Sl  Apr26   3:58 python3 system_telegram_monitor.py
wali      148570  0.1  0.0  30168 19748 pts/18   S    Apr26   5:13 python3 scripts/memory_monitor.py
wali      148571  0.4  0.0  30880 18476 pts/18   S    Apr26  20:10 python3 monitor_system_memory.py
wali      148573  0.1  0.3 18813648 440924 pts/18 Sl  Apr26   5:52 python3 vpn_monitor.py
wali      148574  0.0  0.3 17361732 420632 pts/18 Sl  Apr26   0:29 python3 scripts/ingestors_watchdog.py
wali      148810  2.9  0.3 17911328 473876 pts/19 SNl Apr26 128:29 python3 ingest/live_kucoin.py
wali      148941  0.0  0.2 17205084 362100 pts/19 SNl Apr26   2:28 python3 ingest/live_coinank_global_aggregator.py
wali      148942  0.8  0.2 17202584 358148 pts/19 SNl Apr26  37:06 python3 ingest/liquidation_bridge.py
wali      148943  0.5  0.3 17273132 403852 pts/19 SNl Apr26  21:59 python3 ingest/realtime_price_provider.py
wali      149049  6.5  0.3 18762144 396440 pts/20 SNl Apr26 283:35 python3 -m ingest.live_coinapi_wsds
wali      149111  0.3  0.3 17284232 398304 pts/20 SNl Apr26  14:53 python3 -m ingest.live_coinapi_v1
wali      149186  0.0  0.3 18654276 400344 pts/21 SNl Apr26   1:59 python3 ohlcv_resampler_hotfix.py
wali      149257  3.2  0.3 20019356 479772 pts/21 Sl  Apr26 139:27 python3 feature_pipeline.py
wali      155042  0.5  0.4 17216132 521412 pts/14 Sl+ Apr26  23:50 python3 Desktop/AI BOT/scripts/monitor_trainer_predictions.py
wali      188345  0.0  0.0 1459538620 89060 ?    Sl   Apr27   0:07 /usr/share/cursor/cursor /usr/share/cursor/resources/app/extensions/json-language-features/server/dist/node/jsonServerMain --node-ipc --clientProcessId=133523
wali     2235469  0.0  0.0   8324  2116 pts/11   S+   20:42   0:01 tail -f Desktop/AI BOT/logs/hybrid_trainer.log
wali     2249013  0.0  0.0 1459521516 95940 ?    Sl   21:02   0:00 /usr/share/code/code /usr/share/code/resources/app/extensions/markdown-language-features/dist/serverWorkerMain --node-ipc --clientProcessId=2248850
wali     2249016  0.0  0.0 1459521452 82660 ?    Sl   21:02   0:00 /usr/share/code/code /home/wali/.vscode/extensions/ms-azuretools.vscode-containers-2.4.1/dist/dockerfile-language-server-nodejs/lib/server.js --node-ipc --node-ipc --clientProcessId=2248850
wali     2249025  0.0  0.0 1459521516 81764 ?    Sl   21:02   0:00 /usr/share/code/code /home/wali/.vscode/extensions/ms-azuretools.vscode-containers-2.4.1/dist/compose-language-service/lib/server.js --node-ipc --node-ipc --clientProcessId=2248850
wali     2249034  0.0  0.0  73584  6212 ?        Sl   21:02   0:01 /home/wali/.vscode/extensions/ms-python.vscode-python-envs-1.20.1-linux-x64/python-env-tools/bin/pet server
wali     2249078  0.0  0.0 1459521452 89812 ?    Sl   21:02   0:00 /usr/share/code/code /usr/share/code/resources/app/extensions/json-language-features/server/dist/node/jsonServerMain --node-ipc --clientProcessId=2248850
wali     2250346  0.0  0.0 1459521452 85476 ?    Sl   21:02   0:00 /usr/share/code/code /home/wali/.vscode/extensions/dbaeumer.vscode-eslint-3.0.24/server/out/eslintServer.js --node-ipc --clientProcessId=2248850
wali     2250660  0.5  0.4 1462951028 634956 ?   Sl   21:02   0:51 /usr/share/code/code /home/wali/.vscode/extensions/ms-python.vscode-pylance-2026.2.1/dist/server.bundle.js --cancellationReceive=file:3692000f058eb696189d2d47e9da7a21d0b527d15a --node-ipc --clientProcessId=2248850
wali     2254001  0.0  0.4 17236144 547228 pts/26 Sl+ 21:04   0:05 python3 Desktop/AI BOT/monitor_portfolio_primary.py
redis    2354524 99.7 12.3 22530264 15998704 ?   R    23:28   0:04 redis-rdb-bgsave 127.0.0.1:6379

## Bot process executable/cwd/cmdline mapping

PID=1925
EXE=
CWD=
CMD=/usr/bin/redis-server 127.0.0.1:6379                                            

PID=5131
EXE=/usr/bin/python3.12 (deleted)
CWD=/home/wali/Desktop/AI BOT
CMD=python3 -m rl.orchestrator_worker 

PID=133419
EXE=/usr/share/cursor/cursor
CWD=/home/wali
CMD=/proc/self/exe --type=utility --utility-sub-type=network.mojom.NetworkService --lang=en-US --service-sandbox-type=none --crashpad-handler-pid=133395 --enable-crash-reporter=840f1fb3-4e6c-4da7-a3b1-c054c633c521,no_channel --user-data-dir=/home/wali/.config/Cursor --standard-schemes=vscode-webview,vscode-file --enable-sandbox --secure-schemes=vscode-webview,vscode-file,sentry-ipc --bypasscsp-schemes=sentry-ipc --cors-schemes=vscode-webview,vscode-file,sentry-ipc --fetch-schemes=vscode-webview,vscode-file,sentry-ipc --service-worker-schemes=vscode-webview --code-cache-schemes=vscode-webview,vscode-file --shared-files=v8_context_snapshot_data:100 --field-trial-handle=3,i,6782813967262861978,1761961943262673250,262144 --enable-features=DocumentPolicyIncludeJSCallStacksInCrashReports,PdfUseShowSaveFilePicker --disable-features=CalculateNativeWinOcclusion,LocalNetworkAccessChecks,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708989122997041 

PID=133521
EXE=/usr/share/cursor/cursor
CWD=/home/wali
CMD=/proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --crashpad-handler-pid=133395 --enable-crash-reporter=840f1fb3-4e6c-4da7-a3b1-c054c633c521,no_channel --user-data-dir=/home/wali/.config/Cursor --standard-schemes=vscode-webview,vscode-file --enable-sandbox --secure-schemes=vscode-webview,vscode-file,sentry-ipc --bypasscsp-schemes=sentry-ipc --cors-schemes=vscode-webview,vscode-file,sentry-ipc --fetch-schemes=vscode-webview,vscode-file,sentry-ipc --service-worker-schemes=vscode-webview --code-cache-schemes=vscode-webview,vscode-file --shared-files=v8_context_snapshot_data:100 --field-trial-handle=3,i,6782813967262861978,1761961943262673250,262144 --enable-features=DocumentPolicyIncludeJSCallStacksInCrashReports,PdfUseShowSaveFilePicker --disable-features=CalculateNativeWinOcclusion,LocalNetworkAccessChecks,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708990997080739 

PID=133522
EXE=/usr/share/cursor/cursor
CWD=/home/wali
CMD=/proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --crashpad-handler-pid=133395 --enable-crash-reporter=840f1fb3-4e6c-4da7-a3b1-c054c633c521,no_channel --user-data-dir=/home/wali/.config/Cursor --standard-schemes=vscode-webview,vscode-file --enable-sandbox --secure-schemes=vscode-webview,vscode-file,sentry-ipc --bypasscsp-schemes=sentry-ipc --cors-schemes=vscode-webview,vscode-file,sentry-ipc --fetch-schemes=vscode-webview,vscode-file,sentry-ipc --service-worker-schemes=vscode-webview --code-cache-schemes=vscode-webview,vscode-file --shared-files=v8_context_snapshot_data:100 --field-trial-handle=3,i,6782813967262861978,1761961943262673250,262144 --enable-features=DocumentPolicyIncludeJSCallStacksInCrashReports,PdfUseShowSaveFilePicker --disable-features=CalculateNativeWinOcclusion,LocalNetworkAccessChecks,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708991934122588 

PID=133523
EXE=/usr/share/cursor/cursor
CWD=/home/wali
CMD=/proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --dns-result-order=ipv4first --experimental-network-inspection --inspect-port=0 --crashpad-handler-pid=133395 --enable-crash-reporter=840f1fb3-4e6c-4da7-a3b1-c054c633c521,no_channel --user-data-dir=/home/wali/.config/Cursor --standard-schemes=vscode-webview,vscode-file --enable-sandbox --secure-schemes=vscode-webview,vscode-file,sentry-ipc --bypasscsp-schemes=sentry-ipc --cors-schemes=vscode-webview,vscode-file,sentry-ipc --fetch-schemes=vscode-webview,vscode-file,sentry-ipc --service-worker-schemes=vscode-webview --code-cache-schemes=vscode-webview,vscode-file --shared-files=v8_context_snapshot_data:100 --field-trial-handle=3,i,6782813967262861978,1761961943262673250,262144 --enable-features=DocumentPolicyIncludeJSCallStacksInCrashReports,PdfUseShowSaveFilePicker --disable-features=CalculateNativeWinOcclusion,LocalNetworkAccessChecks,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708992871164437 

PID=133619
EXE=/usr/share/cursor/cursor
CWD=/home/wali
CMD=/proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --crashpad-handler-pid=133395 --enable-crash-reporter=840f1fb3-4e6c-4da7-a3b1-c054c633c521,no_channel --user-data-dir=/home/wali/.config/Cursor --standard-schemes=vscode-webview,vscode-file --enable-sandbox --secure-schemes=vscode-webview,vscode-file,sentry-ipc --bypasscsp-schemes=sentry-ipc --cors-schemes=vscode-webview,vscode-file,sentry-ipc --fetch-schemes=vscode-webview,vscode-file,sentry-ipc --service-worker-schemes=vscode-webview --code-cache-schemes=vscode-webview,vscode-file --shared-files=v8_context_snapshot_data:100 --field-trial-handle=3,i,6782813967262861978,1761961943262673250,262144 --enable-features=DocumentPolicyIncludeJSCallStacksInCrashReports,PdfUseShowSaveFilePicker --disable-features=CalculateNativeWinOcclusion,LocalNetworkAccessChecks,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708993808206286 

PID=133660
EXE=/usr/share/cursor/cursor
CWD=/home/wali
CMD=/proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --dns-result-order=ipv4first --experimental-network-inspection --inspect-port=0 --crashpad-handler-pid=133395 --enable-crash-reporter=840f1fb3-4e6c-4da7-a3b1-c054c633c521,no_channel --user-data-dir=/home/wali/.config/Cursor --standard-schemes=vscode-webview,vscode-file --enable-sandbox --secure-schemes=vscode-webview,vscode-file,sentry-ipc --bypasscsp-schemes=sentry-ipc --cors-schemes=vscode-webview,vscode-file,sentry-ipc --fetch-schemes=vscode-webview,vscode-file,sentry-ipc --service-worker-schemes=vscode-webview --code-cache-schemes=vscode-webview,vscode-file --shared-files=v8_context_snapshot_data:100 --field-trial-handle=3,i,6782813967262861978,1761961943262673250,262144 --enable-features=DocumentPolicyIncludeJSCallStacksInCrashReports,PdfUseShowSaveFilePicker --disable-features=CalculateNativeWinOcclusion,LocalNetworkAccessChecks,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708994745248135 

PID=133661
EXE=/usr/share/cursor/cursor
CWD=/home/wali
CMD=/proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --dns-result-order=ipv4first --experimental-network-inspection --inspect-port=0 --crashpad-handler-pid=133395 --enable-crash-reporter=840f1fb3-4e6c-4da7-a3b1-c054c633c521,no_channel --user-data-dir=/home/wali/.config/Cursor --standard-schemes=vscode-webview,vscode-file --enable-sandbox --secure-schemes=vscode-webview,vscode-file,sentry-ipc --bypasscsp-schemes=sentry-ipc --cors-schemes=vscode-webview,vscode-file,sentry-ipc --fetch-schemes=vscode-webview,vscode-file,sentry-ipc --service-worker-schemes=vscode-webview --code-cache-schemes=vscode-webview,vscode-file --shared-files=v8_context_snapshot_data:100 --field-trial-handle=3,i,6782813967262861978,1761961943262673250,262144 --enable-features=DocumentPolicyIncludeJSCallStacksInCrashReports,PdfUseShowSaveFilePicker --disable-features=CalculateNativeWinOcclusion,LocalNetworkAccessChecks,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708995682289984 

PID=133898
EXE=/usr/share/cursor/cursor
CWD=/home/wali/Desktop/AI BOT
CMD=/usr/share/cursor/cursor /usr/share/cursor/resources/app/extensions/markdown-language-features/dist/serverWorkerMain --node-ipc --clientProcessId=133523 

PID=135296
EXE=/opt/PureVPN/purevpn
CWD=/home/wali
CMD=/opt/PureVPN/purevpn --type=gpu-process --enable-crash-reporter=7bc17627-6576-41c8-bb58-3fcfac62c1c0,no_channel --user-data-dir=/home/wali/.config/purevpn --gpu-preferences=WAAAAAAAAAAgAAAEAAAAAAAAAAAAAAAAAABgAAAAAAA4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABAAAAGAAAAAAAAAAYAAAAAAAAAAgAAAAAAAAACAAAAAAAAAAIAAAAAAAAAA== --shared-files --field-trial-handle=0,i,3805593566275848574,7834192773586567921,262144 --disable-features=SpareRendererForSitePerProcess 

PID=135306
EXE=/opt/PureVPN/purevpn
CWD=/home/wali
CMD=/opt/PureVPN/purevpn --type=utility --utility-sub-type=network.mojom.NetworkService --lang=en-US --service-sandbox-type=none --enable-crash-reporter=7bc17627-6576-41c8-bb58-3fcfac62c1c0,no_channel --user-data-dir=/home/wali/.config/purevpn --shared-files=v8_context_snapshot_data:100 --field-trial-handle=0,i,3805593566275848574,7834192773586567921,262144 --disable-features=SpareRendererForSitePerProcess 

PID=135316
EXE=/opt/PureVPN/purevpn
CWD=
CMD=/opt/PureVPN/purevpn --type=renderer --enable-crash-reporter=7bc17627-6576-41c8-bb58-3fcfac62c1c0,no_channel --user-data-dir=/home/wali/.config/purevpn --app-path=/opt/PureVPN/resources/app.asar --enable-sandbox --first-renderer-process --lang=en-US --num-raster-threads=4 --enable-main-frame-before-activation --renderer-client-id=4 --time-ticks-at-unix-epoch=-1777161738503395 --launch-time-ticks=97268099203 --shared-files=v8_context_snapshot_data:100 --field-trial-handle=0,i,3805593566275848574,7834192773586567921,262144 --disable-features=SpareRendererForSitePerProcess 

PID=135358
EXE=/opt/PureVPN/purevpn
CWD=
CMD=/opt/PureVPN/purevpn --type=renderer --enable-crash-reporter=7bc17627-6576-41c8-bb58-3fcfac62c1c0,no_channel --user-data-dir=/home/wali/.config/purevpn --app-path=/opt/PureVPN/resources/app.asar --enable-sandbox --lang=en-US --num-raster-threads=4 --enable-main-frame-before-activation --renderer-client-id=5 --time-ticks-at-unix-epoch=-1777161738503395 --launch-time-ticks=97268560500 --shared-files=v8_context_snapshot_data:100 --field-trial-handle=0,i,3805593566275848574,7834192773586567921,262144 --disable-features=SpareRendererForSitePerProcess 

PID=137839
EXE=/usr/share/code/code
CWD=/home/wali
CMD=/proc/self/exe --type=utility --utility-sub-type=network.mojom.NetworkService --lang=en-US --service-sandbox-type=none --crashpad-handler-pid=137816 --enable-crash-reporter=56273a96-79c8-475b-8a6c-947b09a8bcf4,no_channel --user-data-dir=/home/wali/.config/Code --standard-schemes=vscode-webview,vscode-file --enable-sandbox --secure-schemes=vscode-webview,vscode-file --cors-schemes=vscode-webview,vscode-file --fetch-schemes=vscode-webview,vscode-file --service-worker-schemes=vscode-webview --code-cache-schemes=vscode-webview,vscode-file --shared-files=v8_context_snapshot_data:100 --field-trial-handle=3,i,8506312766848220127,17544181818425766856,262144 --enable-features=DocumentPolicyIncludeJSCallStacksInCrashReports,EarlyEstablishGpuChannel,EstablishGpuChannelAsync --disable-features=CalculateNativeWinOcclusion,LocalNetworkAccessChecks,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708989122997041 

PID=137941
EXE=/usr/share/code/code
CWD=/home/wali
CMD=/proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --crashpad-handler-pid=137816 --enable-crash-reporter=56273a96-79c8-475b-8a6c-947b09a8bcf4,no_channel --user-data-dir=/home/wali/.config/Code --standard-schemes=vscode-webview,vscode-file --enable-sandbox --secure-schemes=vscode-webview,vscode-file --cors-schemes=vscode-webview,vscode-file --fetch-schemes=vscode-webview,vscode-file --service-worker-schemes=vscode-webview --code-cache-schemes=vscode-webview,vscode-file --shared-files=v8_context_snapshot_data:100 --field-trial-handle=3,i,8506312766848220127,17544181818425766856,262144 --enable-features=DocumentPolicyIncludeJSCallStacksInCrashReports,EarlyEstablishGpuChannel,EstablishGpuChannelAsync --disable-features=CalculateNativeWinOcclusion,LocalNetworkAccessChecks,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708990997080739 

PID=137942
EXE=/usr/share/code/code
CWD=/home/wali
CMD=/proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --crashpad-handler-pid=137816 --enable-crash-reporter=56273a96-79c8-475b-8a6c-947b09a8bcf4,no_channel --user-data-dir=/home/wali/.config/Code --standard-schemes=vscode-webview,vscode-file --enable-sandbox --secure-schemes=vscode-webview,vscode-file --cors-schemes=vscode-webview,vscode-file --fetch-schemes=vscode-webview,vscode-file --service-worker-schemes=vscode-webview --code-cache-schemes=vscode-webview,vscode-file --shared-files=v8_context_snapshot_data:100 --field-trial-handle=3,i,8506312766848220127,17544181818425766856,262144 --enable-features=DocumentPolicyIncludeJSCallStacksInCrashReports,EarlyEstablishGpuChannel,EstablishGpuChannelAsync --disable-features=CalculateNativeWinOcclusion,LocalNetworkAccessChecks,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708991934122588 

PID=138052
EXE=/usr/share/code/code
CWD=/home/wali
CMD=/proc/self/exe --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US --service-sandbox-type=none --crashpad-handler-pid=137816 --enable-crash-reporter=56273a96-79c8-475b-8a6c-947b09a8bcf4,no_channel --user-data-dir=/home/wali/.config/Code --standard-schemes=vscode-webview,vscode-file --enable-sandbox --secure-schemes=vscode-webview,vscode-file --cors-schemes=vscode-webview,vscode-file --fetch-schemes=vscode-webview,vscode-file --service-worker-schemes=vscode-webview --code-cache-schemes=vscode-webview,vscode-file --shared-files=v8_context_snapshot_data:100 --field-trial-handle=3,i,8506312766848220127,17544181818425766856,262144 --enable-features=DocumentPolicyIncludeJSCallStacksInCrashReports,EarlyEstablishGpuChannel,EstablishGpuChannelAsync --disable-features=CalculateNativeWinOcclusion,LocalNetworkAccessChecks,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708993808206286 

PID=142712
EXE=/usr/bin/python3.12 (deleted)
CWD=/home/wali/Desktop/AI BOT
CMD=python3 ingest/live_binance.py 

PID=142970
EXE=/usr/bin/python3.12 (deleted)
CWD=/home/wali/Desktop/AI BOT
CMD=python3 ingest/live_binance_liquidations.py 

PID=143125
EXE=/usr/bin/python3.12 (deleted)
CWD=/home/wali/Desktop/AI BOT
CMD=python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features 

PID=143308
EXE=/usr/bin/python3.12 (deleted)
CWD=/home/wali/Desktop/AI BOT
CMD=python3 trading/trader.py 

PID=146536
EXE=/usr/bin/tail
CWD=/home/wali
CMD=tail -f Desktop/AI BOT/logs/trader.log 

PID=146635
EXE=/usr/bin/tail
CWD=/home/wali
CMD=tail -f Desktop/AI BOT/logs/orchestrator_worker.log 

PID=146815
EXE=/usr/bin/python3.12 (deleted)
CWD=/home/wali/Desktop/AI BOT
CMD=python3 ingest/live_coinank.py 

PID=146816
EXE=/usr/bin/python3.12 (deleted)
CWD=/home/wali/Desktop/AI BOT
CMD=python3 ingest/liquidation_levels_engine.py 

PID=146817
EXE=/usr/bin/python3.12 (deleted)
CWD=/home/wali/Desktop/AI BOT
CMD=python3 ingest/live_technical_analysis.py 

PID=148574
EXE=/usr/bin/python3.12 (deleted)
CWD=/home/wali/Desktop/AI BOT
CMD=python3 scripts/ingestors_watchdog.py 

PID=148810
EXE=/usr/bin/python3.12 (deleted)
CWD=/home/wali/Desktop/AI BOT
CMD=python3 ingest/live_kucoin.py 

PID=148941
EXE=/usr/bin/python3.12 (deleted)
CWD=/home/wali/Desktop/AI BOT
CMD=python3 ingest/live_coinank_global_aggregator.py 

PID=148942
EXE=/usr/bin/python3.12 (deleted)
CWD=/home/wali/Desktop/AI BOT
CMD=python3 ingest/liquidation_bridge.py 

PID=148943
EXE=/usr/bin/python3.12 (deleted)
CWD=/home/wali/Desktop/AI BOT
CMD=python3 ingest/realtime_price_provider.py 

PID=149049
EXE=/usr/bin/python3.12 (deleted)
CWD=/home/wali/Desktop/AI BOT
CMD=python3 -m ingest.live_coinapi_wsds 

PID=149111
EXE=/usr/bin/python3.12 (deleted)
CWD=/home/wali/Desktop/AI BOT
CMD=python3 -m ingest.live_coinapi_v1 

PID=149186
EXE=/usr/bin/python3.12 (deleted)
CWD=/home/wali/Desktop/AI BOT
CMD=python3 ohlcv_resampler_hotfix.py 

PID=149257
EXE=/usr/bin/python3.12 (deleted)
CWD=/home/wali/Desktop/AI BOT
CMD=python3 feature_pipeline.py 

PID=188345
EXE=/usr/share/cursor/cursor
CWD=/home/wali/Desktop/AI BOT
CMD=/usr/share/cursor/cursor /usr/share/cursor/resources/app/extensions/json-language-features/server/dist/node/jsonServerMain --node-ipc --clientProcessId=133523 

PID=2235469
EXE=/usr/bin/tail
CWD=/home/wali
CMD=tail -f Desktop/AI BOT/logs/hybrid_trainer.log 

PID=2249013
EXE=/usr/share/code/code
CWD=/home/wali/Desktop/AI BOT
CMD=/usr/share/code/code /usr/share/code/resources/app/extensions/markdown-language-features/dist/serverWorkerMain --node-ipc --clientProcessId=2248850 

PID=2249078
EXE=/usr/share/code/code
CWD=/home/wali/Desktop/AI BOT
CMD=/usr/share/code/code /usr/share/code/resources/app/extensions/json-language-features/server/dist/node/jsonServerMain --node-ipc --clientProcessId=2248850 

PID=2260770
EXE=/usr/share/code/code
CWD=/home/wali
CMD=/proc/self/exe --type=utility --utility-sub-type=audio.mojom.AudioService --lang=en-US --service-sandbox-type=none --crashpad-handler-pid=137816 --enable-crash-reporter=56273a96-79c8-475b-8a6c-947b09a8bcf4,no_channel --user-data-dir=/home/wali/.config/Code --standard-schemes=vscode-webview,vscode-file --enable-sandbox --secure-schemes=vscode-webview,vscode-file --cors-schemes=vscode-webview,vscode-file --fetch-schemes=vscode-webview,vscode-file --service-worker-schemes=vscode-webview --code-cache-schemes=vscode-webview,vscode-file --shared-files=v8_context_snapshot_data:100 --field-trial-handle=3,i,8506312766848220127,17544181818425766856,262144 --enable-features=DocumentPolicyIncludeJSCallStacksInCrashReports,EarlyEstablishGpuChannel,EstablishGpuChannelAsync --disable-features=CalculateNativeWinOcclusion,LocalNetworkAccessChecks,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708995682289984 

PID=2354524
EXE=
CWD=
CMD=redis-rdb-bgsave 127.0.0.1:6379                                                 
