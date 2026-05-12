# GPU Runtime After Restart

Generated: 2026-05-12T16:50:13Z

Classifications: `GPU_RUNTIME_OBSERVED, TRAINER_USING_GPU, TORCH_CUDA_AVAILABLE`

Trainer PID `3980694` appears in `nvidia-smi --query-compute-apps`: `True`.

## NVIDIA SMI

```text
Tue May 12 12:50:13 2026       
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 580.126.09             Driver Version: 580.126.09     CUDA Version: 13.0     |
+-----------------------------------------+------------------------+----------------------+
| GPU  Name                 Persistence-M | Bus-Id          Disp.A | Volatile Uncorr. ECC |
| Fan  Temp   Perf          Pwr:Usage/Cap |           Memory-Usage | GPU-Util  Compute M. |
|                                         |                        |               MIG M. |
|=========================================+========================+======================|
|   0  NVIDIA GeForce RTX 5080        On  |   00000000:01:00.0  On |                  N/A |
|  0%   49C    P1             61W /  360W |    2207MiB /  16303MiB |      5%      Default |
|                                         |                        |                  N/A |
+-----------------------------------------+------------------------+----------------------+

+-----------------------------------------------------------------------------------------+
| Processes:                                                                              |
|  GPU   GI   CI              PID   Type   Process name                        GPU Memory |
|        ID   ID                                                               Usage      |
|=========================================================================================|
|    0   N/A  N/A         1011574      G   /usr/lib/xorg/Xorg                      256MiB |
|    0   N/A  N/A         1011776      G   .../teamviewer/tv_bin/TeamViewer          5MiB |
|    0   N/A  N/A         1011929      G   /usr/bin/gnome-shell                     40MiB |
|    0   N/A  N/A         1012599      G   ...exec/xdg-desktop-portal-gnome          6MiB |
|    0   N/A  N/A         1012979      G   .../8274/usr/lib/firefox/firefox        183MiB |
|    0   N/A  N/A         1014575      G   /usr/share/code/code                     87MiB |
|    0   N/A  N/A         3064167      G   /usr/bin/nautilus                        14MiB |
|    0   N/A  N/A         3322876      G   /usr/share/cursor/cursor                 69MiB |
|    0   N/A  N/A         3980694      C   python3                                1398MiB |
+-----------------------------------------------------------------------------------------+
```

## Torch Probe

```json
{
  "device_count": 1,
  "device_name": "NVIDIA GeForce RTX 5080",
  "python_version": "3.12.3",
  "torch_cuda_available": true,
  "torch_cuda_version": "12.8",
  "torch_version": "2.8.0+cu128"
}
```

The Torch probe used the local Python interpreter. It did not attach to or modify the running trainer process.
