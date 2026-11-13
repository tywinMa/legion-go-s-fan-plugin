# Legion Go S Fan 0.2.5

在 Steam 游戏模式的快捷菜单打开 Decky → Legion Go S Fan。添加或编辑温度与转速百分比节点后，选「保存并应用」。面板会显示目标和实测 RPM。插件会记住节点和是否启用曲线，在 Decky 启动或设备唤醒后继续应用已启用的曲线。选「恢复自动」会将风扇交回固件，并记住这个选择。

0% 时风扇停转。非零目标转速范围为 1,800–4,200 RPM，100% 对应 4,200 RPM。温度点之间采用线性插值，超出节点范围时沿用最近端点的百分比。驱动在停止接收目标 6 秒后尝试解除接管。当前驱动只支持 Legion Go S 83Q2、BIOS QCCN26WW，v0.2.5 安装包中的模块针对 SteamOS 内核 7.2.7-valve2-2-neptune-72-g31504582a073 编译。

## 安装或更新

先在掌机上安装并启动 Decky Loader。从 [GitHub Releases](https://github.com/tywinMa/legion-go-s-fan-plugin/releases/latest) 下载 `legion-go-s-fan-0.2.5.zip`，解压，在解压后的 `legion-go-s-fan` 目录中打开 Konsole，执行：

```sh
sudo bash install-on-steamos.sh
```

安装脚本会检查机型、BIOS 和内核版本，并重启 Decky Loader。首次安装后，在游戏模式打开 Decky → Legion Go S Fan，选择「保存并应用」后才会启用自定义曲线。已有安装会走更新流程并保留设置。

这个 ZIP 包含需要由 SteamOS 加载的内核模块，请按上述步骤运行安装脚本。

实测设备曾在 v0.2.5 安装后出现一次内置手柄失灵，重启 InputPlumber 后恢复。与风扇驱动的关系尚未确认。

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
