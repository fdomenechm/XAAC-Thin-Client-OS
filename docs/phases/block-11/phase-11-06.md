# Fase 11.6 — Factory reset

Aquesta fase defineix una restauració de fàbrica local, explícita, verificable i auditable. El procés conserva la identitat del dispositiu, l'enrolament, l'auditoria de recuperació i la configuració mínima de xarxa; elimina l'estat del quiosc, les memòries cau, les actualitzacions descarregades, les credencials temporals i les dades d'usuari.

La restauració només pot usar la partició de recuperació signada, es realitza de manera transaccional i requereix administrador local, presència física i la frase exacta `RESET XAAC DEVICE`. No existeix factory reset automàtic ni remot desatés.

Després de restaurar, un servei de primer inici regenera `machine-id`, reaplica la identitat preservada, valida el maquinari, reconcilia l'enrolament i notifica l'Agent. Totes les operacions queden registrades de manera persistent.
