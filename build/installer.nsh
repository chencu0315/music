!macro customInit
  IfFileExists "D:\" 0 customInit_done
  StrCmp $perMachineInstallationFolder "" 0 customInit_done
  StrCpy $INSTDIR "D:\Light Audio Cutter"

  customInit_done:
!macroend
