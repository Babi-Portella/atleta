# Configurar os três requisitos no EMQX Dashboard

Este roteiro reproduz a configuração testada no EMQX 6.1.1. O Compose do kit
preenche esses recursos automaticamente. Use as instruções abaixo quando a
atividade exigir criá-los manualmente pelo painel.

O roteiro descreve uma instância dedicada ao laboratório. Em um broker compartilhado,
as cadeias existentes de autenticação e ACL precisam ser consideradas: a política
global afeta também outros clientes. Não substituir a configuração inteira de uma
instância compartilhada pelo `base.hocon` deste kit.

## 0. Preparar o MySQL e os dados

1. Executar `lab.py init` para gerar as credenciais e o SQL inicial.
2. Em uma instalação MySQL existente, abrir `runtime/01-init.sql` em um cliente
   MySQL e executar com uma conta administrativa, uma vez, para um banco de laboratório
   novo. Na instalação por Compose esse arquivo roda automaticamente no volume vazio.
3. O script cria `athlete_lab`, `telemetry`, `mqtt_users`, `mqtt_acl`, as contas SQL
   `emqx_lab` e `lab_reader` e três contas MQTT. Ele não modifica as tabelas da API.
4. Se essas tabelas/usuários já existirem, conferir seu conteúdo antes de reaplicar
   o seed. Reexecutar os INSERTs não é um procedimento de migração.

Credenciais geradas em `runtime/secrets.json`:

| Chave no arquivo | Uso |
| --- | --- |
| dashboard | Senha de admin da instância criada por este Compose. |
| mysql_root | Administração do MySQL criado pelo Compose. |
| mysql_emqx | Senha SQL de emqx_lab; usada nos três recursos EMQX. |
| mysql_reader | Senha SQL de lab_reader; usada para consultar a persistência. |
| m5-atleta-01 | Senha MQTT da placa. |
| lab-teste-01 | Senha MQTT dos testes automatizados. |
| lab-observer | Senha MQTT do assinante de telemetria. |

Se usar um Dashboard já existente, usar a credencial administrativa dele. O padrão
`admin/public` só se aplica à instalação inicial que ainda o utiliza; a stack deste
kit define uma senha aleatória desde a criação.

Os campos comuns de conexão com MySQL são:

| Campo | Valor |
| --- | --- |
| Server / Server Host | `mysql:3306` entre os containers deste Compose; em outra instalação, endereço do MySQL acessível a partir do EMQX. |
| Database | `athlete_lab` |
| Username | `emqx_lab` |
| Password | Valor da chave `mysql_emqx`. |
| Pool Size | `2` |

Se o EMQX estiver em um container e MySQL em outro, `localhost` não identifica o
outro container. O IP do broker usado pela placa também não é necessariamente o
endereço do banco usado pelo conector.

## 1. Persistência MQTT → MySQL

1. Abrir **Integration → Connectors → Create → MySQL**.
2. Nome: `lab_mysql`. Preencher a conexão com os valores acima.
3. Usar **Test Connectivity** e criar o conector. Deve ficar **Connected**.
4. Abrir **Integration → Rules → Create**. ID: `lab_telemetry`.
5. Colar o conteúdo de [`emqx/rule.sql`](../emqx/rule.sql). A regra recebe
   `atletas/+/telemetria`, seleciona a identidade autenticada e valida os campos
   essenciais do payload. O SELECT deve expor os campos usados pela ação.
6. Usar **Add Action → MySQL → Create Action**. Nome: `lab_save`.
7. Escolher o conector `lab_mysql`.
8. Em SQL Template, colar [`emqx/insert.sql`](../emqx/insert.sql), sem acrescentar
   aspas aos placeholders `${...}` e sem ponto e vírgula no final.
9. Em Advanced Settings: **Batch Size = 1**, **Query Mode = Sync** e
   **Request TTL = 10s**. Criar a ação e salvar a regra.
10. Verificar conector e ação conectados. Após publicação, consultar a tabela:

```sql
SELECT id, received_at, mqtt_username, client_id, topic,
       accel_x_g, accel_y_g, accel_z_g, source
FROM athlete_lab.telemetry
ORDER BY id DESC LIMIT 20;
```

A coluna `source='test'` identifica os dados sintéticos dos testes.
Na demonstração física, filtrar também `mqtt_username='m5-atleta-01'` e
`source='device'`. Uma publicação MQTT aceita não prova, sozinha, gravação no banco.

## 2. Autenticação dos clientes

1. Abrir **Access Control → Authentication → Create**.
2. Mechanism: **Password-Based**. Backend: **MySQL**.
3. Preencher a conexão SQL acima.
4. Password Hash: **bcrypt**. O script já gravou os hashes; não inserir a senha
   em texto puro na coluna `password_hash`.
5. Colar [`emqx/authentication.sql`](../emqx/authentication.sql).
6. Criar e habilitar o autenticador. Na instância dedicada, ele é o único autenticador.

Clientes devem usar estas identidades exatas:

| Cliente | Username | Client ID |
| --- | --- | --- |
| Placa física | m5-atleta-01 | m5-atleta-01 |
| Publicador de testes | lab-teste-01 | lab-teste-01 |
| Assinante de demonstração | lab-observer | lab-observer |

A consulta exige username, Client ID e `enabled=1`. Todos têm `is_superuser=0`;
nenhum ignora a ACL. No MQTTX, desativar a geração automática de Client ID e usar
o valor da tabela. Duas conexões simultâneas com o mesmo Client ID se substituem;
por isso os testes usam uma identidade diferente da placa.

## 3. Autorização / ACL

1. Abrir **Access Control → Authorization → Create → MySQL**.
2. Preencher a conexão SQL acima.
3. Colar [`emqx/authorization.sql`](../emqx/authorization.sql) e habilitar a fonte.
4. Para a instância dedicada: manter somente essa fonte, **No Match = Deny**,
   **Deny Action = Ignore**, **Cache = Disabled**. Isso corresponde à configuração
   testada. Não manter uma regra genérica anterior que libere todos os tópicos.

Permissões cadastradas:

| Usuário | Ação permitida | Tópico |
| --- | --- | --- |
| m5-atleta-01 | publish | atletas/m5-atleta-01/telemetria |
| lab-teste-01 | publish | atletas/lab-teste-01/telemetria |
| lab-observer | subscribe | atletas/+/telemetria |

As demais operações são bloqueadas pela ausência de permissão. Os publicadores
não têm permissão de assinatura. O observador não tem permissão de publicação
nem de assinatura global `#`.

## Testar e apresentar

Os testes do kit usam a mesma versão MQTT 3.1.1 / QoS 0 do firmware e também MQTT 5
para comprovar códigos de recusa de autorização. O script verifica recepção pelo
observador e gravação no MySQL, incluindo ausência de registros para uma publicação
proibida.

Em uma instalação manual, o `verify` pressupõe os nomes de recursos e as credenciais
geradas pelo kit. Executá-lo no servidor com acesso SQL local ou informar as portas
correspondentes. Ele não instala nem substitui as configurações.

```powershell
.\.venv-lab\Scripts\python.exe laboratorio\tools\lab.py verify --host 127.0.0.1 --mqtt-port 1883 --dashboard-port 18083 --mysql-port 33070
```

Para um MySQL nativo, trocar a porta SQL por sua porta real, normalmente `3306`.
Para Dashboard já existente com outra senha, a consulta de verificação exige
adaptar a credencial administrativa privada antes da execução.

Evidências sugeridas: cliente físico conectado, mensagem real recebida, registro
no banco, rejeição de senha errada e bloqueio de tópico proibido. Essas evidências
são uma proposta de demonstração, não um formato de entrega adicional atribuído
ao professor.

## Arquivos gerados para consulta

`runtime/base.hocon` reúne a configuração da stack dedicada. `runtime/emqx-api/`
contém os corpos JSON equivalentes dos recursos. Ambos contêm credenciais locais;
não publicar. `lab.py render --mysql-server IP_DO_MYSQL:3306` pode regenerar esses
arquivos com outro endereço SQL, sem aplicar nada ao servidor.

## Documentação oficial

- [Dashboard](https://docs.emqx.com/en/emqx/latest/dashboard/introduction.html)
- [Persistência MySQL](https://docs.emqx.com/en/emqx/latest/data-integration/data-bridge-mysql.html)
- [Autenticação MySQL](https://docs.emqx.com/en/emqx/latest/access-control/authn/mysql.html)
- [Autorização MySQL](https://docs.emqx.com/en/emqx/latest/access-control/authz/mysql.html)
