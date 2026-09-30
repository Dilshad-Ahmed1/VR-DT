# FIXME: before you push into master...
RUNTIMEDIR=C:/Program Files/OpenModelica1.27.1-64bit/include/omc/c/
#COPY_RUNTIMEFILES=$(FMI_ME_OBJS:%= && (OMCFILE=% && cp $(RUNTIMEDIR)/$$OMCFILE.c $$OMCFILE.c))

fmu:
	rm -f 167.fmutmp/sources/MotorElectroThermalMechanicalFaultable_init.xml
	cp -a "C:/Program Files/OpenModelica1.27.1-64bit/share/omc/runtime/c/fmi/buildproject/"* 167.fmutmp/sources
	cp -a MotorElectroThermalMechanicalFaultable_FMU.libs 167.fmutmp/sources/

