$code = @'
using System;
using System.Runtime.InteropServices;
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {
  int f(); int g(); int h(); int i();
  int SetMasterVolumeLevel(float fLevel, Guid pguidEventContext);
  int SetMasterVolumeLevelScalar(float fLevel, Guid pguidEventContext);
  int GetMasterVolumeLevel(out float pfLevel);
  int GetMasterVolumeLevelScalar(out float pfLevel);
  int j(); int k(); int l(); int m();
  int SetMute([MarshalAs(UnmanagedType.Bool)] bool bMute, Guid pguidEventContext);
  int GetMute(out bool pbMute);
}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice { int Activate(ref Guid id, int clsCtx, IntPtr ap, out IAudioEndpointVolume aev); }
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator { int f(); int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice ep); }
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumeratorComObject { }
public class Audio {
  static IAudioEndpointVolume aev;
  static Audio() {
    var enumerator = new MMDeviceEnumeratorComObject() as IMMDeviceEnumerator;
    IMMDevice dev = null;
    enumerator.GetDefaultAudioEndpoint(0, 1, out dev);
    Guid iid = typeof(IAudioEndpointVolume).GUID;
    dev.Activate(ref iid, 23, IntPtr.Zero, out aev);
  }
  public static float GetVolume() { float v; aev.GetMasterVolumeLevelScalar(out v); return v * 100f; }
  public static bool GetMute() { bool m; aev.GetMute(out m); return m; }
  public static void SetVolume(float pct) { aev.SetMasterVolumeLevelScalar(pct/100f, Guid.Empty); }
  public static void SetMute(bool m) { aev.SetMute(m, Guid.Empty); }
}
'@
Add-Type -TypeDefinition $code -ErrorAction Stop
[Audio]::SetMute($false)
[Audio]::SetVolume(30)
Start-Sleep -Milliseconds 300
$v = [Audio]::GetVolume()
$m = [Audio]::GetMute()
Write-Output ("REAL_VOLUME=" + [math]::Round($v,1))
Write-Output ("REAL_MUTED=" + $m)
