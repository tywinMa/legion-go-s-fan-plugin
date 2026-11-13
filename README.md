# Legion Go S Fan

在 Steam 游戏模式的快捷菜单打开 Decky → Legion Go S Fan。添加或编辑温度与转速百分比节点后，选「保存并应用」。面板会显示目标和实测 RPM。插件会记住节点和是否启用曲线，在 Decky 启动或设备唤醒后继续应用已启用的曲线。选「恢复自动」会将风扇交回固件，并记住这个选择。

0% 时风扇停转。非零目标转速范围为 1,800–4,200 RPM，100% 对应 4,200 RPM。温度点之间采用线性插值，超出节点范围时沿用最近端点的百分比。驱动在停止接收目标 6 秒后尝试解除接管。当前发行包支持 Legion Go S 83Q2、BIOS QCCN26WW、SteamOS 内核 `7.2.7-valve2-2-neptune-72-g31504582a073`。

## 安装或更新

从 v0.2.6 开始，可直接在游戏模式的 Decky Loader 中安装：

1. 打开 Decky 的设置，启用开发者模式并进入「开发者」。
2. 从 [GitHub Releases](https://github.com/tywinMa/legion-go-s-fan-plugin/releases/latest) 下载 Assets 下的 `legion-go-s-fan-<版本>.zip`。在 Decky 选择「从 ZIP 安装」并选中该文件，也可以通过「从 URL 安装」粘贴该 ZIP 的下载链接。
3. 打开 Legion Go S Fan，编辑曲线并选择「保存并应用」。

Decky 会解包插件，插件启动时检查硬件和内核并加载随包提供的驱动。已用旧版脚本安装的设备也可通过 Decky 更新。新驱动加载成功后会停用旧的驱动服务，并继续使用原有曲线。

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

推送到 `main` 会触发 GitHub Actions，自动生成补丁版本，重新构建前端和内核驱动，并将 Decky ZIP 和 SHA-256 校验文件发布到 Releases。版本号写入构建产物，工作流重跑使用同一版本。

驱动的 EC 接口参考了 [Panel de Control 的 Legion Go S 实现](https://github.com/Hooandee/panel-de-control/blob/a510d69/py_modules/fans/legion_ec.py)，驱动源码采用 GPL-3.0-or-later。Decky 插件使用 BSD-3-Clause，详见 LICENSE。
