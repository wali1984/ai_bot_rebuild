# Trainer GPU Runtime Map

Generated: 2026-05-12T06:11:36Z

## Host GPU State

```text
Tue May 12 02:11:36 2026
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 580.126.09             Driver Version: 580.126.09     CUDA Version: 13.0     |
+-----------------------------------------+------------------------+----------------------+
| GPU  Name                 Persistence-M | Bus-Id          Disp.A | Volatile Uncorr. ECC |
| Fan  Temp   Perf          Pwr:Usage/Cap |           Memory-Usage | GPU-Util  Compute M. |
|                                         |                        |               MIG M. |
|=========================================+========================+======================|
|   0  NVIDIA GeForce RTX 5080        On  |   00000000:01:00.0  On |                  N/A |
|  0%   37C    P3             40W /  360W |     896MiB /  16303MiB |     17%      Default |
|                                         |                        |                  N/A |
+-----------------------------------------+------------------------+----------------------+

+-----------------------------------------------------------------------------------------+
| Processes:                                                                              |
|  GPU   GI   CI              PID   Type   Process name                        GPU Memory |
|        ID   ID                                                               Usage      |
|=========================================================================================|
|    0   N/A  N/A         1011574      G   /usr/lib/xorg/Xorg                      264MiB |
|    0   N/A  N/A         1011776      G   .../teamviewer/tv_bin/TeamViewer          5MiB |
|    0   N/A  N/A         1011929      G   /usr/bin/gnome-shell                     40MiB |
|    0   N/A  N/A         1012599      G   ...exec/xdg-desktop-portal-gnome          6MiB |
|    0   N/A  N/A         1012979      G   .../8274/usr/lib/firefox/firefox        259MiB |
|    0   N/A  N/A         1014575      G   /usr/share/code/code                     95MiB |
|    0   N/A  N/A         3064167      G   /usr/bin/nautilus                        14MiB |
|    0   N/A  N/A         3322876      G   /usr/share/cursor/cursor                 51MiB |
+-----------------------------------------------------------------------------------------+
```

## Python/Torch State

```json
{
  "cuda_available": true,
  "device_count": 1,
  "device_name": "NVIDIA GeForce RTX 5080",
  "python_version": "3.12.3",
  "torch_cuda_version": "12.8",
  "torch_version": "2.8.0+cu128"
}
```

## Current Runtime Finding

- GPU visible: `True`.
- Torch CUDA available: `True`.
- Legacy trainer process observed: `False`.
- V2 paper wrapper process observed: `True`.
- Current trainer GPU use proven: `false`.

Classification: `GPU_VISIBLE_BUT_TRAINER_GPU_RUNTIME_NOT_PROVEN`.

Reason: the machine has an RTX 5080 and Torch CUDA is available, but no `rl.hybrid_trainer` process was observed and no current PPO/MASA CUDA inference/training metrics were captured.
