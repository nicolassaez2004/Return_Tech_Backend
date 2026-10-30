# Return Tech

> **Atualização: editor e correção automática.** Leia [INTEGRACAO_JUDGE0.md](INTEGRACAO_JUDGE0.md) para configurar o serviço, testar a demonstração e cadastrar os testes. As configurações adicionais ficam no mesmo `.env` existente do backend, preservando MongoDB e JWT. O frontend mantém apenas o endereço público da API no seu próprio `.env`.

Plataforma que conecta empresas a estudantes e profissionais de cibersegurança por meio de desafios técnicos e processos seletivos baseados em evidências práticas.

O objetivo do projeto não é oferecer uma plataforma educacional como o TryHackMe. O foco é permitir que empresas identifiquem talentos com base no desempenho técnico demonstrado em desafios autorizados.

## Tecnologias

- **Frontend:** React + Vite
- **Backend:** Python + Flask (API REST)
- **Banco de dados:** MongoDB Atlas
- **Autenticação:** JWT
- **Armazenamento de arquivos:** GridFS do MongoDB

## Estrutura do projeto

O sistema está dividido em dois repositórios/pastas:

```text
Return_Tech_Frontend/
Return_Tech_Backend/
```

## Requisitos

Antes de começar, instale:

- Node.js;
- Python 3.11 ou superior;
- Visual Studio Code ou outro editor de código;
- Git, caso o projeto seja obtido pelo GitHub.

Também é necessária uma conexão com a internet para acessar o MongoDB Atlas.

> O Docker Desktop não é obrigatório. O banco principal do projeto está no MongoDB Atlas.

---

# Configuração do backend

## 1. Arquivo `.env`

O `.env` do backend contém informações privadas de acesso ao banco e não está no GitHub.

Se ele já está configurado, continue usando esse mesmo arquivo. Esta revisão acrescenta somente `JUDGE0_URL`, `JUDGE0_API_KEY`, `JUDGE0_RAPIDAPI_HOST` e `JUDGE0_AUTH_TOKEN`, inicialmente vazios. Preencha os campos do seu provedor quando tiver o acesso real; não substitua MongoDB nem JWT pelos valores de um modelo. Remova o antigo `.env.example` caso ainda esteja na pasta.

Solicite esse arquivo à pessoa responsável pelo projeto e coloque-o diretamente na pasta `Return_Tech_Backend`, no mesmo nível de `run.py`:

```text
Return_Tech_Backend/
├── .env
├── run.py
├── requirements.txt
└── app/
```

O arquivo possui esta estrutura:

```env
MONGO_URI=mongodb+srv://USUARIO:SENHA@ENDERECO/return_tech?PARAMETROS
JWT_SECRET_KEY=CHAVE_SECRETA
FRONTEND_URL=http://localhost:5173
```

Não substitua os valores acima manualmente. Utilize o `.env` enviado de forma privada pela equipe.

Regras de segurança:

- nunca envie o `.env` para o GitHub;
- nunca publique a `MONGO_URI`, pois ela contém as credenciais do banco;
- confirme que `.env` está listado no `.gitignore`;
- não envie capturas de tela que mostrem a senha do Atlas.

## 2. Autorizar o acesso ao MongoDB Atlas

O computador precisa estar autorizado no Atlas para acessar o banco compartilhado.

Se ocorrer erro de conexão, a pessoa responsável pelo projeto deve acessar:

```text
MongoDB Atlas → Security → Network Access
```

Depois, deve adicionar o endereço IP atual do integrante. A permissão do usuário dentro do painel do Atlas e as credenciais usadas pelo backend são controles diferentes.

## 3. Criar o ambiente virtual

Abra a pasta `Return_Tech_Backend` no VS Code e abra um terminal PowerShell.

Na primeira execução, crie o ambiente virtual:

```powershell
python -m venv .venv
```

## 4. Ativar o ambiente virtual

```powershell
.venv\Scripts\Activate.ps1
```

Quando estiver ativo, o terminal começará com:

```text
(.venv)
```

Se o PowerShell bloquear a ativação, execute primeiro:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Depois, tente ativar a `.venv` novamente.

## 5. Instalar as dependências

Na primeira execução, ou sempre que o `requirements.txt` for alterado:

```powershell
pip install -r requirements.txt
```

## 6. Iniciar o backend

```powershell
python run.py
```

O backend ficará disponível em:

```text
http://127.0.0.1:5000
```

Para testar a API, abra:

```text
http://127.0.0.1:5000/api/health
```

Resultado esperado:

```json
{
  "service": "return-tech-api",
  "status": "ok"
}
```

Não feche esse terminal enquanto estiver utilizando o sistema.

---

# Configuração do frontend

Abra a pasta `Return_Tech_Frontend` em outra janela do VS Code ou use um segundo terminal.

## 1. Instalar as dependências

Na primeira execução:

```powershell
npm install
```

## 2. Iniciar o frontend

```powershell
npm run dev
```

O frontend ficará disponível em:

```text
http://localhost:5173
```

O `.env` existente do frontend contém apenas `VITE_API_URL=http://localhost:5000/api`. O mesmo endereço é usado como padrão quando essa variável está ausente. Credenciais do MongoDB, JWT e Judge0 ficam somente no `.env` do backend.

Não feche esse terminal enquanto estiver utilizando o sistema.

---

# Ordem para iniciar o sistema

## Primeira execução

### Terminal 1 — Backend

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

### Terminal 2 — Frontend

```powershell
npm install
npm run dev
```

Depois, abra:

```text
http://localhost:5173
```

## Próximas execuções

### Terminal 1 — Backend

```powershell
.venv\Scripts\Activate.ps1
python run.py
```

### Terminal 2 — Frontend

```powershell
npm run dev
```

O MongoDB Atlas permanece disponível na nuvem. Não é necessário executar `docker compose up -d`.

---

# Como testar o fluxo completo

1. Crie uma conta do tipo **Empresa**.
2. Cadastre as informações da empresa.
3. Crie e publique um desafio de cibersegurança.
4. Abra uma janela anônima do navegador.
5. Crie uma conta do tipo **Estudante/Profissional**.
6. Entre no desafio e envie uma solução.
7. Volte para a conta da empresa.
8. Avalie a entrega e, se desejar, adicione o participante à shortlist.

A janela anônima permite manter as duas contas conectadas simultaneamente.

Como todos utilizam o mesmo banco no Atlas, contas, desafios, participações e avaliações ficam disponíveis para os integrantes autorizados.

---

# Como encerrar

Nos terminais do Flask e do React, pressione:

```text
Ctrl + C
```

Não é necessário desligar o MongoDB Atlas.

---

# Problemas comuns

## O backend não inicia ou não conecta ao Atlas

Confirme se:

- o `.env` está dentro da pasta `Return_Tech_Backend`;
- a `MONGO_URI` está completa;
- o endereço contém `/return_tech` depois de `.mongodb.net/`;
- o IP do computador está autorizado em **Network Access**;
- o computador está conectado à internet.

## Erro `NoneType object has no attribute users`

Esse erro normalmente significa que a `MONGO_URI` não contém o nome do banco.

O trecho:

```text
.mongodb.net/?
```

deve estar como:

```text
.mongodb.net/return_tech?
```

Não publique a conexão completa ao pedir ajuda.

## A página `http://127.0.0.1:5000` mostra 404

Isso é normal. O backend não possui uma página visual na rota principal.

Use:

```text
http://127.0.0.1:5000/api/health
```

## O site abre, mas cadastro e login não funcionam

Confirme se:

- o Flask está rodando na porta `5000`;
- o React está rodando na porta `5173`;
- `http://127.0.0.1:5000/api/health` retorna `status: ok`;
- o navegador está acessando `http://localhost:5173`.

## O frontend não abre

Confirme se o terminal do frontend mostra:

```text
Local: http://localhost:5173/
```

Se as dependências ainda não tiverem sido instaladas, execute:

```powershell
npm install
npm run dev
```

## O PowerShell não ativa a `.venv`

Execute:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

Essa alteração vale apenas para o terminal atual.

---

# Docker como alternativa opcional

O arquivo `docker-compose.yml` pode permanecer no backend para permitir testes com um banco MongoDB local. Ele não é necessário no fluxo principal com o Atlas.

Para usar o banco local, seria necessário alterar temporariamente a `MONGO_URI` para:

```env
MONGO_URI=mongodb://localhost:27017/return_tech
```

E iniciar o MongoDB com:

```powershell
docker compose up -d
```

Os dados do Docker são locais e não são compartilhados com os outros integrantes. Não execute esse comando quando estiver usando a `MONGO_URI` do Atlas.

---

# Funcionamento do sistema

## Fluxo principal

1. A empresa cria um desafio ou processo seletivo.
2. A empresa define competências, nível, modelo de trabalho, prazo e entregáveis.
3. Estudantes e profissionais criam seus perfis e participam dos desafios.
4. Os participantes enviam soluções e evidências técnicas em ambientes autorizados.
5. A empresa avalia as entregas e registra pontuação e feedback.
6. Os candidatos selecionados podem ser adicionados à shortlist.

## Frontend

Interface minimalista e profissional, com temática de cibersegurança e fluxos separados para:

- empresas;
- estudantes e profissionais.

## Backend

API REST desenvolvida em Flask, responsável por:

- autenticação com JWT;
- gerenciamento de usuários e perfis;
- criação e publicação de desafios;
- participação e envio de soluções;
- avaliações e feedbacks;
- portfólio de evidências;
- shortlist de candidatos;
- notificações;
- armazenamento de arquivos no GridFS do MongoDB.

---

# Estado atual

O Return Tech é um MVP funcional para desenvolvimento e testes. O frontend e o backend ainda são executados localmente, enquanto o banco de dados é compartilhado pelo MongoDB Atlas.

Para disponibilizar o sistema publicamente, ainda será necessário hospedar o frontend e o backend, configurar HTTPS, restringir acessos e revisar as configurações de segurança para produção.
