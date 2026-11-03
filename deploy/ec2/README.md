# Deploy em uma EC2 Ubuntu existente

Estes arquivos preparam a aplicação para a instância já fornecida pela disciplina,
seguindo o [guia de deploy](https://insper.github.io/ProgramacaoEficaz/aulas/06-Deploy/).
Não criam recursos AWS, não alteram security groups ou UFW, não instalam Docker
e não reiniciam o servidor. O instalador é executado somente após autorização e
confirmação do endereço, acesso SSH e capacidade da instância.

O host precisa estar reservado para esta aplicação. Antes de executar o instalador,
confira os sites NGINX existentes e o destino atual do domínio ou IP. Acrescentar
um `server_name` pode capturar tráfego antes atendido pelo site padrão, mesmo sem
apagar sua configuração. Se o IP já atende outro trabalho, use um domínio ou
subdomínio dedicado e autorizado; não presuma que o endereço antigo está livre.
A opção `--host-confirmed` registra essa pré-condição e não substitui a inspeção
nem a autorização para publicar.

## Arquitetura e pré-requisitos

- Ubuntu 22.04 ou 24.04 amd64, com acesso `sudo` autorizado.
- Backend em `/opt/returntech/backend`; build do frontend em `/var/www/returntech`.
- Frontend compilado com `VITE_API_URL=/api`.
- Arquivo privado `/etc/returntech/backend.env`, com proprietário root e modo 0600.
- MongoDB Atlas acessível a partir do IP de saída da EC2 e usuário autorizado no banco.
- Python 3.10 ou superior. `requirements-production.txt` inclui as dependências do
  projeto e [Gunicorn 26.2.0, verificado no PyPI](https://pypi.org/project/gunicorn/26.2.0/).

O NGINX recebe HTTP na porta 80, entrega os arquivos estáticos e encaminha
`/api/...` sem remover o prefixo para o Gunicorn em `127.0.0.1:8000`.
Há dois workers independentes para emails/prazos e correção de código.
O frontend usa as rotas atuais e o fluxo de aprovação dos desafios é preservado.

O serviço da API usa um worker Gunicorn com duas threads, sem carregar o aplicativo
antes do fork. Esse perfil reduz o consumo numa instância pequena que também
hospeda outro trabalho. O NGINX serve o build produzido localmente; não é necessário
instalar Node.js ou `node_modules` no servidor. Confira a memória disponível após
iniciar os três serviços, preservando a aplicação anterior.

## Entregar a versão revisada

Use um pacote da versão local revisada, em vez de clonar uma versão antiga do GitHub.
Os comandos abaixo são um roteiro; substitua os marcadores pelos dados confirmados.

Na máquina local, envie o pacote sanitizado preparado para este deploy:

```text
scp -i CAMINHO_DA_CHAVE pacote-deploy.tar.gz ubuntu@HOST_PUBLICO:/tmp/
```

No servidor, confira o conteúdo do pacote antes de extraí-lo. Ele deve conter
`backend/` e `frontend/`, sem `.env`, chaves SSH, `.git`, `.venv`, `node_modules`
ou credenciais. Não sobreponha outra aplicação existente sem revisão.

```bash
tar -tzf /tmp/pacote-deploy.tar.gz
mkdir -p /tmp/returntech-release
tar -xzf /tmp/pacote-deploy.tar.gz -C /tmp/returntech-release
sudo install -d -m 0755 /opt/returntech/backend /var/www/returntech
sudo cp -a /tmp/returntech-release/backend/. /opt/returntech/backend/
sudo cp -a /tmp/returntech-release/frontend/. /var/www/returntech/
```

Ao atualizar uma instalação existente, o instalador reaproveita a `.venv` e
substitui apenas seus próprios serviços e site NGINX. Ele não apaga arquivos
estáticos antigos nem configurações de outros sites. Faça uma cópia da versão
anterior antes de entregar uma atualização.

## Configuração privada

Crie o arquivo diretamente no servidor ou envie-o por SSH separado do pacote.
Use linhas `NOME=valor`, sem `export`; não execute o arquivo como script.

```bash
sudo install -d -m 0750 /etc/returntech
sudo install -m 0600 /dev/null /etc/returntech/backend.env
sudoedit /etc/returntech/backend.env
```

O comando `install /dev/null` é somente para a criação inicial. Não o repita em
uma instalação configurada, pois ele esvazia o arquivo existente.

Preencha os valores reais nesse arquivo privado, sem imprimi-los em logs:

```env
FLASK_DEBUG=0
PORT=8000
MONGO_URI=mongodb+srv://USUARIO:SENHA@CLUSTER/BANCO
JWT_SECRET_KEY=CHAVE_ALEATORIA_COM_PELO_MENOS_32_CARACTERES
FRONTEND_URL=http://HOST_PUBLICO
MAIL_APP_URL=http://HOST_PUBLICO
CHALLENGE_TIMEZONE=America/Sao_Paulo
BACKGROUND_JOBS_ENABLED=false
JOBS_INTERVAL_SECONDS=30
MAIL_ENABLED=false
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USE_SSL=false
MAIL_USERNAME=
MAIL_PASSWORD=
MAIL_FROM=
MAIL_FROM_NAME=Return Tech
JUDGE0_URL=
JUDGE0_API_KEY=
JUDGE0_RAPIDAPI_HOST=
JUDGE0_AUTH_TOKEN=
```

Gere uma chave JWT privada nova; não utilize literalmente o marcador acima.
Use as credenciais corretas do Atlas e mantenha a lista de IPs do Atlas restrita
ao IP de saída autorizado da instância. Mudanças no IP público exigem revisar
essa lista e `FRONTEND_URL`. Os links dos emails usam essa origem pública.
Para enviar emails, configure o remetente e a senha de aplicativo SMTP e então
defina `MAIL_ENABLED=true`.

Sem certificado, o instalador seleciona `nginx.conf`, com HTTP e suporte ao desafio
ACME. Quando o certificado e sua chave existem em `/etc/letsencrypt/live/HOST_PUBLICO/`,
seleciona `nginx-https.conf`, com HTTPS e redirecionamento HTTP para HTTPS.

## Instalar e verificar

```bash
cd /opt/returntech/backend
sudo bash deploy/ec2/install.sh HOST_PUBLICO --host-confirmed
systemctl is-active returntech-api returntech-mailworker returntech-codeworker nginx
curl --fail http://127.0.0.1:8000/api/health
curl --fail http://HOST_PUBLICO/api/health
```

O instalador mantém outros sites NGINX e somente recarrega após `nginx -t`.
Uma falha no teste restaura o arquivo anterior deste aplicativo. No security
group, conforme o guia, autorize SSH/22 apenas para o IP de administração e
HTTP/80 para acesso ao site. Não exponha 8000, 5000 ou 2358 publicamente.

Para diagnosticar um serviço, consulte `systemctl status NOME_DO_SERVICO` e
`journalctl -u NOME_DO_SERVICO`, preservando qualquer dado privado presente nos logs.
Após atualizar o ambiente privado, reinicie os três serviços Return Tech.

## Habilitar HTTPS com certificado legítimo

Use um domínio ou subdomínio confirmado que aponte para a instância e esteja
reservado para esta aplicação. O host precisa responder ao desafio HTTP na porta 80.
O prefixo `/.well-known/acme-challenge/` já está liberado nos dois templates NGINX,
antes do bloqueio de arquivos ocultos. Não utilize certificados fictícios nem
desative a verificação de segurança do navegador.

Com o site HTTP previamente validado, os comandos de preparação são:

```bash
sudo apt-get update
sudo apt-get install -y certbot
sudo certbot certonly --webroot -w /var/www/returntech -d HOST_PUBLICO --cert-name HOST_PUBLICO
sudo bash /opt/returntech/backend/deploy/ec2/install.sh HOST_PUBLICO --host-confirmed
```

O Certbot solicita os dados de registro necessários; não coloque senhas nem
credenciais da aplicação no comando. O instalador só ativa o template HTTPS se
`fullchain.pem` e `privkey.pem` existirem para esse host, testa `nginx -t` e preserva
as configurações dos outros sites.

A porta TCP 443 também precisa estar autorizada no security group da EC2, além
do firewall local. Essa autorização deve ser feita por quem possui acesso legítimo
à conta AWS ou pelo responsável da disciplina. Liberar UFW isoladamente não altera
o security group; não tente contornar essa restrição usando portas de outro serviço.

Confirme o acesso de uma máquina externa à instância:

```bash
curl --fail https://HOST_PUBLICO/api/health
```

Somente após o endereço HTTPS responder corretamente, altere `FRONTEND_URL` para
`https://HOST_PUBLICO` no ambiente privado e reinicie os três serviços Return Tech.
Assim, as regras de origem e os links enviados por email passam a usar o endereço
seguro que efetivamente está disponível.

Para recarregar o NGINX depois das renovações bem-sucedidas do Certbot:

```bash
sudo install -d -m 0755 /etc/letsencrypt/renewal-hooks/deploy
sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-returntech-nginx >/dev/null <<'HOOK'
#!/bin/sh
set -eu
/usr/sbin/nginx -t
/bin/systemctl reload nginx
HOOK
sudo chmod 0755 /etc/letsencrypt/renewal-hooks/deploy/reload-returntech-nginx
sudo certbot renew --cert-name HOST_PUBLICO --dry-run
```

Confira também o timer de renovação instalado pelo pacote Certbot. Os certificados,
as contas ACME e as chaves privadas permanecem em `/etc/letsencrypt`, fora do Git
e dos pacotes da aplicação. Este roteiro não executa ações na AWS automaticamente.

## HTTPS temporário por Cloudflare Quick Tunnel

O Quick Tunnel é uma alternativa temporária autorizada para publicar este site
com HTTPS. O navegador se conecta à Cloudflare; a Cloudflare encaminha todo o
tráfego do site e da API, inclusive login, até a aplicação na EC2 pelo túnel.
Isso não torna pública a porta 8000 e não exige entrada TCP 443 no security group
da instância. O site anterior `projeto2` permanece com sua configuração existente.

Nesta implantação, o `cloudflared` oficial 2026.10.7 foi instalado manualmente
após conferir o SHA-256. O serviço opcional `returntech-web-tunnel.service` usa
`http://127.0.0.1:80` como origem e envia o cabeçalho Host do site Return Tech
reservado no NGINX. Ele não faz parte dos três serviços iniciados pelo instalador
padrão. O Gunicorn continua em `127.0.0.1:8000`, com um worker e duas threads.

Neste fluxo, mantenha o template NGINX HTTP como origem interna do túnel, sem
redirecionar para o hostname nip.io por HTTPS. O template `nginx-https.conf` é uma
alternativa futura para domínio e porta 443 devidamente preparados; não deve ser
aplicado automaticamente a esta implantação com Quick Tunnel.

O endereço `trycloudflare.com` não é estável: um novo início do processo pode gerar
outra URL. A URL utilizada nesta execução foi
`https://min-parties-blair-confirmed.trycloudflare.com`; ela não é uma promessa de
endereço permanente nem um túnel nomeado de conta Cloudflare.

Depois de reiniciar o serviço, consulte a URL anunciada no início mais recente:

```bash
sudo journalctl -u returntech-web-tunnel -b --no-pager |
  grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -n 1
```

Se a URL mudar, atualize somente `FRONTEND_URL` em
`/etc/returntech/backend.env` com a nova origem HTTPS, sem acrescentar `/api`, e
reinicie os três serviços da aplicação:

```bash
sudoedit /etc/returntech/backend.env
sudo systemctl restart returntech-api returntech-mailworker returntech-codeworker
```

O arquivo `/var/lib/returntech/public-url.txt` registra apenas a última URL
configurada. Ele não acompanha automaticamente uma mudança de endereço do
Quick Tunnel e não substitui a atualização do ambiente. Confira o novo endereço
e `/api/health` antes de compartilhá-lo; os links dos emails também dependem de
`FRONTEND_URL` estar correto.

O túnel temporário do Judge0 é independente deste túnel web. O computador, a VM
Judge0 e seu iniciador SSH precisam continuar ligados para a correção de código.
O site e os demais recursos da EC2 não passam a depender do computador para
servir suas páginas. A liberação legítima da porta 443 pelo responsável da AWS,
com domínio e certificado válidos, continua sendo uma opção futura mais estável.

## Judge0: preparação separada

O endereço `127.0.0.1:2358` usado no Windows aponta para a instalação daquele
computador; ele não fornece um executor à EC2. Para executar os desafios no site,
é necessário disponibilizar uma instalação Judge0 compatível no servidor ou um
endpoint HTTPS autorizado, com seu token privado no ambiente do backend.

A instalação oficial do [Judge0 CE 1.13.1](https://github.com/judge0/judge0/releases/tag/v1.13.1)
recomenda Ubuntu 22.04 e configurações específicas de cgroups/GRUB que podem
exigir reinicialização. Seus containers utilizam privilégios elevados. Por isso,
o instalador da aplicação não instala o executor, não muda o kernel e não assume
que a EC2 fornecida tem memória, disco ou permissões suficientes.

Quando o executor estiver no mesmo host, publique sua API somente em loopback e
use `JUDGE0_URL=http://127.0.0.1:2358`. Para executor remoto, o cliente exige HTTPS.
Nunca exponha PostgreSQL/Redis do Judge0 ou copie credenciais para o frontend.
