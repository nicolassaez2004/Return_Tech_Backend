# Return Tech

Plataforma que conecta estudantes e profissionais a empresas por meio de desafios e processos seletivos na área de cibersegurança.

## Tecnologias

- Frontend: React + Vite
- Backend: Python + Flask
- Banco de dados: MongoDB
- Banco local: Docker
- Autenticação: JWT

## Estrutura

```text
Return_Tech_Frontend/
Return_Tech_Backend/
```

## Requisitos

Antes de começar, instale:

- Node.js 22 ou superior
- Python 3.11 ou superior
- Docker Desktop
- Visual Studio Code

## Arquivo `.env`

O arquivo `.env` do backend não está no GitHub por segurança.

Solicite o arquivo `.env` à responsável pelo projeto e coloque-o diretamente dentro da pasta:

```text
Return_Tech_Backend/
├── .env
├── run.py
├── requirements.txt
└── docker-compose.yml
```

Nunca envie o `.env` para o GitHub.

---

# Como executar o backend

Abra a pasta `Return_Tech_Backend` no VS Code e abra um terminal PowerShell.

Execute cada comando separadamente.

## 1. Criar o ambiente virtual

Esta etapa só precisa ser feita na primeira execução:

```powershell
python -m venv .venv
```

## 2. Ativar o ambiente virtual

```powershell
.venv\Scripts\Activate.ps1
```

Quando estiver ativo, o terminal apresentará:

```text
(.venv)
```

## 3. Instalar as dependências

Esta etapa só precisa ser feita na primeira execução ou quando o `requirements.txt` mudar:

```powershell
pip install -r requirements.txt
```

## 4. Iniciar o MongoDB

Abra o Docker Desktop e espere o Docker Engine iniciar.

Depois, no terminal do backend:

```powershell
docker compose up -d
```

Confira se o MongoDB está funcionando:

```powershell
docker ps
```

Deve aparecer um contêiner chamado:

```text
return-tech-mongo
```

## 5. Iniciar o Flask

```powershell
python run.py
```

O backend ficará disponível em:

```text
http://127.0.0.1:5000
```

Para testar a API, acesse:

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

# Como executar o frontend

Abra a pasta `Return_Tech_Frontend` em outra janela do VS Code ou abra um segundo terminal.

## 1. Instalar as dependências

Esta etapa só precisa ser feita na primeira execução:

```powershell
npm install
```

## 2. Iniciar o React

```powershell
npm run dev
```

O frontend ficará disponível em:

```text
http://localhost:5173
```

Não feche esse terminal enquanto estiver utilizando o sistema.

---

# Ordem para iniciar o sistema

Sempre execute nesta ordem:

1. Abrir o Docker Desktop.
2. Executar `docker compose up -d` no backend.
3. Ativar a `.venv`.
4. Executar `python run.py`.
5. Executar `npm run dev` no frontend.
6. Abrir `http://localhost:5173`.

São necessários dois terminais:

- Terminal 1: backend Flask;
- Terminal 2: frontend React.

---

# Como testar o fluxo completo

1. Crie uma conta do tipo Empresa.
2. Cadastre um desafio de cibersegurança e envie para aprovação.
3. Entre como administrador e aprove a publicação do desafio.
4. Abra uma janela anônima do navegador.
5. Crie uma conta de Estudante/Profissional.
6. Entre no desafio aprovado e envie uma solução.
7. Volte para a conta da empresa.
8. Avalie a entrega e adicione o participante à shortlist.

A janela anônima é necessária para manter duas contas conectadas simultaneamente.

---

# Como encerrar

Nos terminais do Flask e React, pressione:

```text
Ctrl + C
```

Para parar o MongoDB, execute na pasta do backend:

```powershell
docker compose stop
```

Os dados permanecerão salvos no volume do Docker.

---

# Próximas execuções

Não é necessário instalar tudo novamente.

## Backend

```powershell
.venv\Scripts\Activate.ps1
docker compose up -d
python run.py
```

## Frontend

```powershell
npm run dev
```

---

# Problemas comuns

## Erro `dockerDesktopLinuxEngine`

O Docker Desktop não está ligado. Abra-o e aguarde o Engine iniciar.

## Erro de conexão com `localhost:27017`

O MongoDB não está funcionando. Execute:

```powershell
docker compose up -d
```

## A página `http://127.0.0.1:5000` mostra 404

Isso é normal. O backend não possui página visual na rota principal.

Use:

```text
http://127.0.0.1:5000/api/health
```

## O frontend não abre

Confirme se o terminal mostra:

```text
Local: http://localhost:5173
```

## O site abre, mas cadastro e login não funcionam

Confirme se:

- Docker Desktop está aberto;
- `return-tech-mongo` aparece no `docker ps`;
- Flask está rodando na porta 5000;
- React está rodando na porta 5173.

## PROPOSTA

Faremos uma plataforma que conecta empresas a profissionais de cibersegurança por meio de desafios técnicos, competições e avaliações práticas. O MVP deve padronizar a operação de caça-talentos, para profissionais de tecnologia. Empresas sobem desafios de cibersegurança e definem competências desejadas.

NOSSA OPERAÇÃO:

- Elaborar competições de cibersegurança.
- Solicitar a empresas Desafios e habilidades profissionais demandadas.
- Profissionais e estudantes de segurança participam do processo seletivo.
- Desempenho técnico é avaliado.
- Empresas identificam candidatos qualificados através de nossa operação.
- Moldamos uma comunidade de profissionais de cibersegurança.

OBS: O objetivo não é ser voltado para educação (como um try hack me), mas sim para caçar talentos através de desempenho técnico avaliado. 

## FLUXO

1. Empresa cria uma competição:
- Define cargo.
- Competências.
- Prazo. 

2. Talentos se inscrevem:
- Criam perfis.
- Participam voluntariamente.

3. Participantes resolvem desafios:
- Submetem respostas ou flags em ambientes autorizados.

4. Plataforma avalia resultados:
- Pontuação.
- Competências.
- Desempenho por desafio.

5. Empresa identifica candidatos:
- Consulta perfis autorizados
- Convida talentos para entrevistas.

## FRONT-END

Devemos fazer um front-end minimalista e profissional, com temática simples de cibersegurança.

## BACK-END

A definir...

## Administração dos CTFs

Há três perfis separados: `company` cadastra e envia seus próprios desafios para aprovação;
`talent` consulta os publicados, participa e envia soluções; `admin` é reservado
à equipe Return Tech e administra os desafios de todas as empresas.

O cadastro público aceita somente empresas e talentos. Para cada integrante do
grupo, crie uma conta administrativa exclusiva no terminal do backend, com o
ambiente virtual ativado e a conexão ao MongoDB configurada:

```powershell
python -m flask --app run.py create-admin
```

O comando solicita nome, e-mail e senha, confirma a senha sem exibi-la e salva
apenas o hash. Ele não promove contas existentes. Depois, entre com essa conta
em `http://localhost:5173/#/admin`. Para uso fora do computador local, publique
frontend e backend na hospedagem escolhida e utilize o endereço do frontend
seguido de `/#/admin`.

No painel, a equipe pode buscar e filtrar CTFs, abrir o enunciado, editar os
campos, aprovar publicações, solicitar ajustes, encerrar ou retirar da publicação para rascunho.
O desafio continua associado à empresa que o criou. Os exemplos fictícios
continuam definidos no frontend e não são registros do banco de dados.

### Rotas acrescentadas

- `GET /api/challenges/<id>`: detalhes do desafio; rascunhos ficam restritos à
  empresa responsável e à administração. Participantes podem consultar um
  desafio encerrado, mas não enviar novas soluções.
- `PATCH /api/challenges/<id>`: editar enunciado e metadados, pela empresa
  responsável ou por um administrador.
- `GET /api/admin/challenges`: listar todos os desafios, apenas para `admin`.
- `PATCH /api/challenges/<id>/status`: também aceita administradores; a ação
  `draft`, a aprovação e a solicitação de ajustes são exclusivas deles.

### Testes sem usar o banco real

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Os testes usam um banco em memória para verificar os fluxos e as permissões.


## Fluxo de aprovação dos desafios

- `draft` → `pending_review`: a empresa responsável usa `submit_review`.
- `pending_review` → `published`: somente `admin`, com ação `approve` e
  `review_revision` igual à revisão do enunciado que foi exibida ao revisor.
- `pending_review` → `changes_requested`: somente `admin`, com ação
  `request_changes`, `review_revision` e justificativa `feedback` obrigatória.
- A empresa pode editar os campos e reenviar os ajustes ou um desafio encerrado.
  Alterações reais da empresa invalidam a aprovação e devolvem o desafio a `draft`.
- A ação antiga `publish` de empresa apenas solicita a revisão; ela nunca publica.
  Para administrador, `publish` é um alias de `approve`, com as mesmas validações.
- Apenas `published` aparece para novos talentos. Pendentes não permitem consulta
  direta, inscrição ou envio de soluções. Participações encerradas continuam consultáveis.
- A aprovação registra administrador, data e revisão. Uma revisão antiga ou uma
  alteração concorrente recebe HTTP 409, exigindo atualizar e revisar o enunciado.
- A empresa recebe uma notificação quando o desafio é aprovado ou precisa de ajustes.

O código não modifica retroativamente os registros que já estavam publicados.
Os testes em memória cobrem os estados, as permissões, a nova aprovação após
alterações e a proteção contra publicação de conteúdo ainda não revisado.
