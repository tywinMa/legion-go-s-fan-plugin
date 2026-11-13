# Legion Go S Fan 0.2.5

在 Steam 游戏模式的快捷菜单打开 Decky → Legion Go S Fan。添加或编辑温度与转速百分比节点后，选「保存并应用」。面板会显示目标和实测 RPM。插件会记住节点和是否启用曲线，在 Decky 启动或设备唤醒后继续应用已启用的曲线。选「恢复自动」会将风扇交回固件，并记住这个选择。

0% 时风扇停转。非零目标转速范围为 1,800–4,200 RPM，100% 对应 4,200 RPM。温度点之间采用线性插值，超出节点范围时沿用最近端点的百分比。驱动在停止接收目标 6 秒后尝试解除接管。当前驱动只支持 Legion Go S 83Q2、BIOS QCCN26WW，v0.2.5 安装包中的模块针对 SteamOS 内核 7.2.7-valve2-2-neptune-72-g31504582a073 编译。

## 更新已有的 0.1.1 安装

使用 v0.2.5 安装包，或先按下文构建源码，再在掌机上执行 `sudo bash upgrade.sh`。可加 `--verify` 在设备空闲时验证实际转速响应和恢复自动。测试使用临时配置，保留已有温度节点。更新过程会重新启动 Decky。

## 构建

在安装了目标 SteamOS 内核构建头文件的 Linux 环境中编译驱动。

```sh
pnpm install --frozen-lockfile
pnpm check
pnpm build
make -C /lib/modules/"$(uname -r)"/build M="$PWD/driver" modules
cp driver/legion_go_s_fan.ko .
```

驱动的 EC 接口参考了 [Panel de Control 的 Legion Go S 实现](https://github.com/Hooandee/panel-de-control/blob/a510d69/py_modules/fans/legion_ec.py)，驱动源码采用 GPL-3.0-or-later。Decky 插件使用 BSD-3-Clause，详见 LICENSE。
