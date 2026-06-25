!macro customInstall
  DetailPrint "Registering backend Windows service..."
  nsExec::ExecToLog '"$INSTDIR\resources\backend-dist\ali-backend-service.exe" install --startup auto'
  Pop $0
  DetailPrint "Service install exit code: $0"

  nsExec::ExecToLog 'sc start AliAutoPublishBackend'
  Pop $1
  DetailPrint "Service start exit code: $1"
!macroend

!macro customUnInstall
  DetailPrint "Stopping backend Windows service..."
  nsExec::ExecToLog 'sc stop AliAutoPublishBackend'
  Pop $0
  DetailPrint "Service stop exit code: $0"

  DetailPrint "Removing backend Windows service..."
  nsExec::ExecToLog '"$INSTDIR\resources\backend-dist\ali-backend-service.exe" remove'
  Pop $1
  DetailPrint "Service remove exit code: $1"
!macroend
